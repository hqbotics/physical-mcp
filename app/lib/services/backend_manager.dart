import 'dart:async';
import 'dart:io';

import 'package:flutter/foundation.dart';

/// Lifecycle state of the embedded backend process.
enum BackendState {
  stopped,
  starting,
  running,
  error,
}

/// Manages the embedded Python backend process lifecycle.
///
/// On macOS, the PyInstaller binary lives at:
///   Physical MCP.app/Contents/Resources/physical-mcp-server
///
/// The manager detects if the binary exists, starts it as a subprocess,
/// polls the health endpoint until ready, and kills it on app exit.
class BackendManager {
  final int port;
  final int mcpPort;
  final void Function(BackendState state)? onStateChanged;

  Process? _process;
  BackendState _state = BackendState.stopped;
  String? _errorMessage;
  Timer? _watchdogTimer;
  final List<String> _recentErrors = [];

  BackendManager({this.port = 8090, this.mcpPort = 8400, this.onStateChanged});

  BackendState get state => _state;
  String? get errorMessage => _errorMessage;

  /// Recent camera/permission errors from the backend subprocess.
  List<String> get recentErrors => List.unmodifiable(_recentErrors);

  /// Path to the embedded backend binary inside the app bundle.
  String get _binaryPath {
    if (Platform.isMacOS) {
      // Platform.resolvedExecutable → .../Contents/MacOS/Physical MCP
      // Resources at → .../Contents/Resources/
      final execDir = File(Platform.resolvedExecutable).parent.path;
      return '$execDir/../Resources/physical-mcp-server';
    }
    if (Platform.isWindows) {
      return '${File(Platform.resolvedExecutable).parent.path}\\physical-mcp-server.exe';
    }
    // Linux: same directory as binary
    return '${File(Platform.resolvedExecutable).parent.path}/physical-mcp-server';
  }

  /// Whether the embedded backend binary exists in the app bundle.
  bool get isEmbedded {
    final exists = File(_binaryPath).existsSync();
    debugPrint('[BackendManager] Binary at $_binaryPath exists=$exists');
    return exists;
  }

  /// Check if a backend (embedded or external) is already running.
  Future<bool> isAlreadyRunning() async {
    try {
      final client = HttpClient();
      client.connectionTimeout = const Duration(seconds: 2);
      final request = await client
          .getUrl(Uri.parse('http://127.0.0.1:$port/health'))
          .timeout(const Duration(seconds: 3));
      final response = await request.close().timeout(const Duration(seconds: 3));
      client.close(force: true);
      return response.statusCode == 200;
    } catch (_) {
      return false;
    }
  }

  /// Check if the MCP server (streamable-HTTP) is responding on [mcpPort].
  ///
  /// The MCP endpoint returns 405/406 on GET (it expects POST with specific
  /// Accept headers). Any of these status codes means uvicorn is alive and
  /// ready to serve ChatGPT / other MCP clients.
  Future<bool> isMcpReady() async {
    try {
      final client = HttpClient();
      client.connectionTimeout = const Duration(seconds: 2);
      final request = await client
          .getUrl(Uri.parse('http://127.0.0.1:$mcpPort/mcp'))
          .timeout(const Duration(seconds: 3));
      final response = await request.close().timeout(const Duration(seconds: 3));
      client.close(force: true);
      // MCP returns 405 (Method Not Allowed) or 406 (Not Acceptable) on GET
      // because it expects POST with Accept: application/json, text/event-stream.
      // Any response means the server is alive.
      return response.statusCode == 405 ||
          response.statusCode == 406 ||
          response.statusCode == 200;
    } catch (_) {
      return false;
    }
  }

  /// Start the embedded backend. Returns true if started successfully.
  ///
  /// If a backend is already running on the port, returns true immediately.
  /// If the binary doesn't exist, returns false with error state.
  Future<bool> start() async {
    // Already running (user started from terminal, or previous instance)
    if (await isAlreadyRunning()) {
      debugPrint('[BackendManager] Backend already running on port $port');
      _setState(BackendState.running);
      return true;
    }

    // No embedded binary
    if (!isEmbedded) {
      _errorMessage = 'Backend binary not found at $_binaryPath';
      debugPrint('[BackendManager] $_errorMessage');
      _setState(BackendState.error);
      return false;
    }

    _setState(BackendState.starting);
    debugPrint('[BackendManager] Starting embedded backend...');

    try {
      // Ensure binary is executable
      if (!Platform.isWindows) {
        await Process.run('chmod', ['+x', _binaryPath]);
      }

      // Spawn the backend process
      _process = await Process.start(
        _binaryPath,
        ['--port', port.toString(), '--mcp-port', mcpPort.toString()],
        mode: ProcessStartMode.normal,
      );

      debugPrint('[BackendManager] Process started, PID=${_process!.pid}');

      // Log stdout/stderr for debugging
      _process!.stdout.listen((data) {
        final msg = String.fromCharCodes(data).trim();
        if (msg.isNotEmpty) debugPrint('[Backend] $msg');
      });
      _process!.stderr.listen((data) {
        final msg = String.fromCharCodes(data).trim();
        if (msg.isNotEmpty) {
          debugPrint('[Backend ERR] $msg');
          // Capture camera/permission errors for UI display
          final lower = msg.toLowerCase();
          if (lower.contains('camera') ||
              lower.contains('no cameras') ||
              lower.contains('failed to open') ||
              lower.contains('tcc') ||
              lower.contains('permission') ||
              lower.contains('not authorized')) {
            _recentErrors.add(msg);
            if (_recentErrors.length > 10) _recentErrors.removeAt(0);
          }
        }
      });

      // Monitor process exit
      _process!.exitCode.then((code) {
        debugPrint('[BackendManager] Process exited with code $code');
        if (_state == BackendState.running) {
          _errorMessage = 'Backend process exited unexpectedly (code $code)';
          _setState(BackendState.error);
        }
      });

      // Poll Vision API health endpoint until ready (up to 90 seconds)
      // PyInstaller --onefile cold start can take 30-60s on first launch
      bool visionReady = false;
      for (int i = 0; i < 180; i++) {
        await Future.delayed(const Duration(milliseconds: 500));
        if (await isAlreadyRunning()) {
          debugPrint('[BackendManager] Vision API healthy after ${(i + 1) * 500}ms');
          visionReady = true;
          break;
        }
      }

      if (!visionReady) {
        _errorMessage = 'Backend started but health check timed out after 90s';
        debugPrint('[BackendManager] $_errorMessage');
        _setState(BackendState.error);
        return false;
      }

      // Also wait for MCP server (uvicorn on mcpPort) — starts a few seconds
      // after Vision API. This prevents the tunnel from connecting to a port
      // that isn't ready yet, which causes Cloudflare error pages.
      debugPrint('[BackendManager] Vision API ready, waiting for MCP server on port $mcpPort...');
      for (int i = 0; i < 60; i++) {
        await Future.delayed(const Duration(milliseconds: 500));
        if (await isMcpReady()) {
          debugPrint('[BackendManager] MCP server ready on port $mcpPort after ${(i + 1) * 500}ms');
          _setState(BackendState.running);
          _startWatchdog();
          return true;
        }
      }

      // MCP didn't start within 30s — Vision API still works,
      // but tunnel/ChatGPT won't work. Report running with warning.
      debugPrint('[BackendManager] WARNING: MCP server not ready after 30s (Vision API OK)');
      _setState(BackendState.running);
      _startWatchdog();
      return true;
    } catch (e) {
      _errorMessage = 'Failed to start backend: $e';
      debugPrint('[BackendManager] $_errorMessage');
      _setState(BackendState.error);
      return false;
    }
  }

  /// Stop the embedded backend process.
  Future<void> stop() async {
    _watchdogTimer?.cancel();
    _watchdogTimer = null;

    if (_process != null) {
      debugPrint('[BackendManager] Stopping backend (PID=${_process!.pid})...');
      _process!.kill(ProcessSignal.sigterm);
      try {
        await _process!.exitCode.timeout(const Duration(seconds: 5));
        debugPrint('[BackendManager] Backend stopped gracefully');
      } catch (_) {
        debugPrint('[BackendManager] Force killing backend...');
        _process!.kill(ProcessSignal.sigkill);
      }
      _process = null;
    }
    _setState(BackendState.stopped);
  }

  /// Restart the backend (stop then start).
  Future<bool> restart() async {
    await stop();
    await Future.delayed(const Duration(seconds: 1));
    return start();
  }

  /// Periodic watchdog — restart if the backend crashes.
  void _startWatchdog() {
    _watchdogTimer?.cancel();
    _watchdogTimer = Timer.periodic(const Duration(seconds: 30), (_) async {
      if (_state != BackendState.running) return;
      final healthy = await isAlreadyRunning();
      if (!healthy) {
        debugPrint('[BackendManager] Watchdog: backend unhealthy, restarting...');
        _setState(BackendState.starting);
        await start();
      }
    });
  }

  void _setState(BackendState newState) {
    if (_state == newState) return;
    _state = newState;
    debugPrint('[BackendManager] State: $newState');
    onStateChanged?.call(newState);
  }

  /// Clean up — stops the process and cancels timers.
  void dispose() {
    _watchdogTimer?.cancel();
    _watchdogTimer = null;
    if (_process != null) {
      _process!.kill(ProcessSignal.sigterm);
      _process = null;
    }
  }
}
