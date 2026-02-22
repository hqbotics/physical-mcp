import 'dart:async';
import 'dart:io';

import 'package:flutter/foundation.dart';

/// State of the Cloudflare/ngrok tunnel process.
enum TunnelState {
  stopped,
  starting,
  running,
  error,
}

/// Manages a Cloudflare Tunnel (or ngrok fallback) subprocess that exposes
/// the local Vision API over HTTPS for ChatGPT and other cloud AI services.
///
/// ChatGPT **requires** a public HTTPS URL — it cannot reach LAN IPs.
/// Cloudflare's free "trycloudflare.com" quick tunnel provides this
/// without signup or configuration.
///
/// Usage:
/// ```dart
/// final tunnel = TunnelManager();
/// await tunnel.start(port: 8090);
/// print(tunnel.publicUrl);  // https://demo-123.trycloudflare.com
/// print(tunnel.mcpUrl);     // https://demo-123.trycloudflare.com/mcp
/// ```
class TunnelManager {
  final void Function(TunnelState state, String? url)? onStateChanged;

  Process? _process;
  String? _publicUrl;
  TunnelState _state = TunnelState.stopped;
  String? _errorMessage;
  Timer? _watchdogTimer;
  int _port = 8090;

  TunnelManager({this.onStateChanged});

  TunnelState get state => _state;
  String? get errorMessage => _errorMessage;

  /// The public HTTPS URL (e.g. https://demo-123.trycloudflare.com)
  String? get publicUrl => _publicUrl;

  /// The MCP endpoint URL for ChatGPT (e.g. https://demo-123.trycloudflare.com/mcp)
  String? get mcpUrl => _publicUrl != null ? '$_publicUrl/mcp' : null;

  /// Whether cloudflared is available on the system.
  static Future<bool> isCloudflaredInstalled() async {
    final path = await _findCloudflared();
    return path != null;
  }

  /// Find cloudflared binary path.
  static Future<String?> _findCloudflared() async {
    // Try `which` first
    try {
      final result = await Process.run('which', ['cloudflared']);
      final path = result.stdout.toString().trim();
      if (path.isNotEmpty && File(path).existsSync()) {
        return path;
      }
    } catch (_) {}

    // Check common paths
    for (final candidate in [
      '/opt/homebrew/bin/cloudflared',
      '/usr/local/bin/cloudflared',
      '/usr/bin/cloudflared',
    ]) {
      if (File(candidate).existsSync()) return candidate;
    }

    return null;
  }

  /// Start the Cloudflare Tunnel. Returns true if the tunnel started
  /// and a public HTTPS URL was obtained.
  Future<bool> start({int port = 8090}) async {
    if (_state == TunnelState.running && _publicUrl != null) {
      debugPrint('[TunnelManager] Already running: $_publicUrl');
      return true;
    }

    _port = port;
    _setState(TunnelState.starting);
    _publicUrl = null;
    _errorMessage = null;

    final cloudflared = await _findCloudflared();
    if (cloudflared == null) {
      _errorMessage =
          'cloudflared not found. Install it:\nbrew install cloudflare/cloudflare/cloudflared';
      debugPrint('[TunnelManager] $_errorMessage');
      _setState(TunnelState.error);
      return false;
    }

    debugPrint('[TunnelManager] Starting tunnel via $cloudflared to localhost:$port...');

    try {
      _process = await Process.start(
        cloudflared,
        ['tunnel', '--url', 'http://localhost:$port'],
        mode: ProcessStartMode.normal,
      );

      debugPrint('[TunnelManager] Process started, PID=${_process!.pid}');

      // cloudflared outputs the public URL to stderr
      final completer = Completer<String?>();
      final urlRegex = RegExp(r'https://[a-zA-Z0-9.-]+\.trycloudflare\.com');

      // Listen to both stdout and stderr — cloudflared uses stderr for the URL
      void scanLine(String line) {
        if (completer.isCompleted) return;
        debugPrint('[Tunnel] $line');
        final match = urlRegex.firstMatch(line);
        if (match != null) {
          completer.complete(match.group(0));
        }
      }

      _process!.stdout.listen((data) {
        for (final line in String.fromCharCodes(data).split('\n')) {
          if (line.trim().isNotEmpty) scanLine(line.trim());
        }
      });
      _process!.stderr.listen((data) {
        for (final line in String.fromCharCodes(data).split('\n')) {
          if (line.trim().isNotEmpty) scanLine(line.trim());
        }
      });

      // Monitor process exit
      _process!.exitCode.then((code) {
        debugPrint('[TunnelManager] Process exited with code $code');
        if (_state == TunnelState.running) {
          _errorMessage = 'Tunnel process exited (code $code)';
          _setState(TunnelState.error);
          _publicUrl = null;
        }
      });

      // Wait up to 20 seconds for the URL
      String? url;
      try {
        url = await completer.future.timeout(const Duration(seconds: 20));
      } on TimeoutException {
        debugPrint('[TunnelManager] Timeout waiting for tunnel URL');
      }

      if (url != null) {
        _publicUrl = url;
        debugPrint('[TunnelManager] Public URL: $url');
        _setState(TunnelState.running);
        _startWatchdog();
        return true;
      } else {
        _errorMessage = 'Could not obtain tunnel URL within 20 seconds';
        debugPrint('[TunnelManager] $_errorMessage');
        _setState(TunnelState.error);
        // Kill the process since we can't use it
        _process?.kill(ProcessSignal.sigterm);
        _process = null;
        return false;
      }
    } catch (e) {
      _errorMessage = 'Failed to start tunnel: $e';
      debugPrint('[TunnelManager] $_errorMessage');
      _setState(TunnelState.error);
      return false;
    }
  }

  /// Stop the tunnel process.
  Future<void> stop() async {
    _watchdogTimer?.cancel();
    _watchdogTimer = null;

    if (_process != null) {
      debugPrint('[TunnelManager] Stopping tunnel (PID=${_process!.pid})...');
      _process!.kill(ProcessSignal.sigterm);
      try {
        await _process!.exitCode.timeout(const Duration(seconds: 5));
      } catch (_) {
        _process!.kill(ProcessSignal.sigkill);
      }
      _process = null;
    }

    _publicUrl = null;
    _setState(TunnelState.stopped);
  }

  /// Restart the tunnel.
  Future<bool> restart() async {
    await stop();
    await Future.delayed(const Duration(seconds: 1));
    return start(port: _port);
  }

  /// Watchdog: if the tunnel process dies, try to restart.
  void _startWatchdog() {
    _watchdogTimer?.cancel();
    _watchdogTimer = Timer.periodic(const Duration(seconds: 30), (_) async {
      if (_state != TunnelState.running) return;
      // Check if process is still alive
      if (_process == null) {
        debugPrint('[TunnelManager] Watchdog: process gone, restarting...');
        _setState(TunnelState.starting);
        await start(port: _port);
      }
    });
  }

  void _setState(TunnelState newState) {
    if (_state == newState) return;
    _state = newState;
    debugPrint('[TunnelManager] State: $newState');
    onStateChanged?.call(newState, _publicUrl);
  }

  /// Clean up — stops the tunnel process and cancels timers.
  void dispose() {
    _watchdogTimer?.cancel();
    _watchdogTimer = null;
    if (_process != null) {
      _process!.kill(ProcessSignal.sigterm);
      _process = null;
    }
    _publicUrl = null;
  }
}
