import 'dart:async';

import 'package:nsd/nsd.dart';

import '../models/server_config.dart';

/// Discovers physical-mcp servers on the local network via mDNS.
class MdnsDiscovery {
  static const String _serviceType = '_http._tcp';
  static const Duration _scanDuration = Duration(seconds: 5);

  Discovery? _discovery;
  final StreamController<ServerConfig> _controller =
      StreamController<ServerConfig>.broadcast();

  /// Stream of discovered servers.
  Stream<ServerConfig> get onDiscovered => _controller.stream;

  /// Start scanning for physical-mcp servers on the network.
  ///
  /// Returns a list of discovered servers after [timeout] duration.
  Future<List<ServerConfig>> scan({
    Duration timeout = _scanDuration,
  }) async {
    final discovered = <ServerConfig>[];
    final completer = Completer<List<ServerConfig>>();

    try {
      _discovery = await startDiscovery(_serviceType);

      _discovery!.addServiceListener((service, status) {
        if (status == ServiceStatus.found) {
          // Check if this is a physical-mcp service
          final name = service.name?.toLowerCase() ?? '';
          if (name.contains('physical') || name.contains('mcp')) {
            final host = service.host ?? service.name ?? '';
            final port = service.port ?? 8090;

            if (host.isNotEmpty) {
              final config = ServerConfig(
                name: service.name ?? 'Physical MCP',
                host: host,
                port: port,
                isDiscovered: true,
              );

              if (!discovered.any((s) => s.host == config.host)) {
                discovered.add(config);
                _controller.add(config);
              }
            }
          }
        }
      });

      // Wait for scan duration then return results.
      await Future.delayed(timeout);
      await stop();

      if (!completer.isCompleted) {
        completer.complete(discovered);
      }
    } catch (e) {
      await stop();
      if (!completer.isCompleted) {
        completer.complete(discovered);
      }
    }

    return completer.future;
  }

  /// Try to connect to a known host:port directly.
  Future<ServerConfig?> tryDirect(String host, {int port = 8090}) async {
    try {
      final config = ServerConfig(
        name: 'Physical MCP',
        host: host,
        port: port,
      );

      // We'll validate connectivity through the ApiClient.
      return config;
    } catch (_) {
      return null;
    }
  }

  /// Stop any active discovery.
  Future<void> stop() async {
    if (_discovery != null) {
      try {
        await stopDiscovery(_discovery!);
      } catch (_) {
        // Ignore errors during cleanup
      }
      _discovery = null;
    }
  }

  void dispose() {
    stop();
    _controller.close();
  }
}
