import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;

import '../models/server_config.dart';

/// Server-Sent Events client for real-time updates from the backend.
class SseClient {
  final ServerConfig config;
  final http.Client _http;

  StreamSubscription<String>? _subscription;
  final StreamController<SseEvent> _controller =
      StreamController<SseEvent>.broadcast();

  bool _connected = false;
  Timer? _reconnectTimer;

  SseClient({required this.config, http.Client? httpClient})
      : _http = httpClient ?? http.Client();

  /// Stream of SSE events.
  Stream<SseEvent> get events => _controller.stream;

  /// Whether currently connected.
  bool get isConnected => _connected;

  /// Connect to the SSE endpoint.
  Future<void> connect() async {
    if (_connected) return;

    try {
      final request = http.Request(
        'GET',
        Uri.parse('${config.baseUrl}/events'),
      );
      config.headers.forEach((key, value) {
        request.headers[key] = value;
      });
      request.headers['Accept'] = 'text/event-stream';
      request.headers['Cache-Control'] = 'no-cache';

      final streamedResponse = await _http.send(request);

      if (streamedResponse.statusCode != 200) {
        throw Exception(
            'SSE connection failed: ${streamedResponse.statusCode}');
      }

      _connected = true;
      _controller.add(const SseEvent(type: 'connected', data: ''));

      String buffer = '';

      _subscription = streamedResponse.stream
          .transform(utf8.decoder)
          .listen(
        (chunk) {
          buffer += chunk;
          // Parse SSE events from buffer
          while (buffer.contains('\n\n')) {
            final idx = buffer.indexOf('\n\n');
            final eventStr = buffer.substring(0, idx);
            buffer = buffer.substring(idx + 2);

            final event = _parseEvent(eventStr);
            if (event != null) {
              _controller.add(event);
            }
          }
        },
        onError: (error) {
          _connected = false;
          _controller.add(SseEvent(
              type: 'error', data: error.toString()));
          _scheduleReconnect();
        },
        onDone: () {
          _connected = false;
          _controller
              .add(const SseEvent(type: 'disconnected', data: ''));
          _scheduleReconnect();
        },
        cancelOnError: false,
      );
    } catch (e) {
      _connected = false;
      _controller.add(SseEvent(type: 'error', data: e.toString()));
      _scheduleReconnect();
    }
  }

  /// Parse a single SSE event string.
  SseEvent? _parseEvent(String eventStr) {
    String type = 'message';
    String data = '';

    for (final line in eventStr.split('\n')) {
      if (line.startsWith('event:')) {
        type = line.substring(6).trim();
      } else if (line.startsWith('data:')) {
        data = line.substring(5).trim();
      }
    }

    if (data.isEmpty && type == 'message') return null;

    return SseEvent(type: type, data: data);
  }

  /// Schedule a reconnection attempt.
  void _scheduleReconnect() {
    _reconnectTimer?.cancel();
    _reconnectTimer = Timer(const Duration(seconds: 3), () {
      if (!_connected) {
        connect();
      }
    });
  }

  /// Disconnect from SSE.
  Future<void> disconnect() async {
    _reconnectTimer?.cancel();
    await _subscription?.cancel();
    _subscription = null;
    _connected = false;
  }

  void dispose() {
    disconnect();
    _controller.close();
    _http.close();
  }
}

/// A single SSE event.
class SseEvent {
  final String type;
  final String data;

  const SseEvent({required this.type, required this.data});

  /// Try to parse the data as JSON.
  Map<String, dynamic>? get json {
    try {
      return jsonDecode(data) as Map<String, dynamic>;
    } catch (_) {
      return null;
    }
  }

  @override
  String toString() => 'SseEvent($type: $data)';
}
