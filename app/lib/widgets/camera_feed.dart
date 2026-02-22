import 'dart:async';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;

import '../theme/dji_theme.dart';

/// Custom MJPEG stream widget that renders live camera feeds.
///
/// Connects to the physical-mcp /stream endpoint and continuously
/// renders JPEG frames. Handles connection errors, automatic
/// reconnection, and frame rate management.
class CameraFeed extends StatefulWidget {
  final String streamUrl;
  final Map<String, String>? headers;
  final BoxFit fit;
  final Widget? placeholder;
  final Widget? errorWidget;
  final bool showFps;
  final Duration reconnectDelay;

  const CameraFeed({
    super.key,
    required this.streamUrl,
    this.headers,
    this.fit = BoxFit.cover,
    this.placeholder,
    this.errorWidget,
    this.showFps = false,
    this.reconnectDelay = const Duration(seconds: 2),
  });

  @override
  State<CameraFeed> createState() => _CameraFeedState();
}

class _CameraFeedState extends State<CameraFeed> {
  Uint8List? _currentFrame;
  bool _isConnected = false;
  bool _hasError = false;
  int _fps = 0;
  int _frameCount = 0;
  Timer? _fpsTimer;
  http.Client? _httpClient;
  StreamSubscription<List<int>>? _subscription;
  bool _disposed = false;

  @override
  void initState() {
    super.initState();
    _connect();
    if (widget.showFps) {
      _fpsTimer = Timer.periodic(const Duration(seconds: 1), (_) {
        if (!_disposed) {
          setState(() {
            _fps = _frameCount;
            _frameCount = 0;
          });
        }
      });
    }
  }

  @override
  void didUpdateWidget(CameraFeed oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.streamUrl != widget.streamUrl) {
      _disconnect();
      _connect();
    }
  }

  @override
  void dispose() {
    _disposed = true;
    _fpsTimer?.cancel();
    _disconnect();
    super.dispose();
  }

  void _connect() async {
    _httpClient = http.Client();
    try {
      final request = http.Request('GET', Uri.parse(widget.streamUrl));
      widget.headers?.forEach((key, value) {
        request.headers[key] = value;
      });

      final response = await _httpClient!.send(request);

      if (response.statusCode != 200) {
        if (!_disposed) {
          setState(() {
            _hasError = true;
            // HTTP error
          });
        }
        _scheduleReconnect();
        return;
      }

      if (!_disposed) {
        setState(() {
          _isConnected = true;
          _hasError = false;
        });
      }

      // Parse MJPEG multipart stream
      final boundary = _extractBoundary(
          response.headers['content-type'] ?? '');

      if (boundary != null) {
        _parseMjpegStream(response.stream, boundary);
      } else {
        // Fallback: try to parse as raw JPEG stream
        _parseRawJpegStream(response.stream);
      }
    } catch (e) {
      if (!_disposed) {
        setState(() {
          _hasError = true;
          // Connection error
          _isConnected = false;
        });
      }
      _scheduleReconnect();
    }
  }

  String? _extractBoundary(String contentType) {
    // e.g. multipart/x-mixed-replace;boundary=frame
    final match =
        RegExp(r'boundary=(.+)').firstMatch(contentType);
    return match?.group(1);
  }

  void _parseMjpegStream(
      Stream<List<int>> stream, String boundary) {
    final buffer = BytesBuilder();
    bool inFrame = false;

    _subscription = stream.listen(
      (chunk) {
        for (int i = 0; i < chunk.length; i++) {
          buffer.addByte(chunk[i]);

          final bytes = buffer.toBytes();

          // Check for JPEG start marker (FFD8)
          if (!inFrame &&
              bytes.length >= 2 &&
              bytes[bytes.length - 2] == 0xFF &&
              bytes[bytes.length - 1] == 0xD8) {
            buffer.clear();
            buffer.addByte(0xFF);
            buffer.addByte(0xD8);
            inFrame = true;
          }

          // Check for JPEG end marker (FFD9)
          if (inFrame &&
              bytes.length >= 2 &&
              bytes[bytes.length - 2] == 0xFF &&
              bytes[bytes.length - 1] == 0xD9) {
            final frame = Uint8List.fromList(buffer.toBytes());
            buffer.clear();
            inFrame = false;
            _onFrame(frame);
          }
        }
      },
      onError: (_) {
        if (!_disposed) {
          setState(() {
            _isConnected = false;
            _hasError = true;
          });
        }
        _scheduleReconnect();
      },
      onDone: () {
        if (!_disposed) {
          setState(() => _isConnected = false);
        }
        _scheduleReconnect();
      },
      cancelOnError: false,
    );
  }

  void _parseRawJpegStream(Stream<List<int>> stream) {
    // Simple: just try to display each chunk if it looks like a JPEG
    final buffer = BytesBuilder();

    _subscription = stream.listen(
      (chunk) {
        buffer.add(chunk);
        final bytes = buffer.toBytes();

        // Look for JPEG end marker
        for (int i = 1; i < bytes.length; i++) {
          if (bytes[i - 1] == 0xFF && bytes[i] == 0xD9) {
            // Find start marker
            int start = 0;
            for (int j = 0; j < bytes.length - 1; j++) {
              if (bytes[j] == 0xFF && bytes[j + 1] == 0xD8) {
                start = j;
                break;
              }
            }
            final frame =
                Uint8List.fromList(bytes.sublist(start, i + 1));
            buffer.clear();
            if (i + 1 < bytes.length) {
              buffer.add(bytes.sublist(i + 1));
            }
            _onFrame(frame);
            break;
          }
        }
      },
      onError: (_) => _scheduleReconnect(),
      onDone: () => _scheduleReconnect(),
    );
  }

  void _onFrame(Uint8List frame) {
    if (_disposed) return;
    _frameCount++;
    setState(() {
      _currentFrame = frame;
    });
  }

  void _disconnect() {
    _subscription?.cancel();
    _subscription = null;
    _httpClient?.close();
    _httpClient = null;
    _isConnected = false;
  }

  void _scheduleReconnect() {
    if (_disposed) return;
    Future.delayed(widget.reconnectDelay, () {
      if (!_disposed && !_isConnected) {
        _disconnect();
        _connect();
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    return Stack(
      fit: StackFit.expand,
      children: [
        // Camera frame or placeholder
        if (_currentFrame != null)
          Image.memory(
            _currentFrame!,
            fit: widget.fit,
            gaplessPlayback: true, // Prevent flicker between frames
          )
        else if (_hasError)
          widget.errorWidget ??
              Center(
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Icon(
                      Icons.videocam_off_rounded,
                      size: 48,
                      color: DJIColors.textTertiary,
                    ),
                    const SizedBox(height: DJISpacing.sm),
                    Text(
                      'Camera offline',
                      style: TextStyle(
                        color: DJIColors.textTertiary,
                        fontSize: 13,
                      ),
                    ),
                  ],
                ),
              )
        else
          widget.placeholder ??
              const Center(
                child: CircularProgressIndicator(
                  color: DJIColors.primary,
                  strokeWidth: 2,
                ),
              ),

        // FPS counter
        if (widget.showFps && _isConnected)
          Positioned(
            top: 8,
            right: 8,
            child: Container(
              padding: const EdgeInsets.symmetric(
                  horizontal: 6, vertical: 2),
              decoration: BoxDecoration(
                color: Colors.black.withValues(alpha: 0.6),
                borderRadius: BorderRadius.circular(4),
              ),
              child: Text(
                '${_fps}fps',
                style: const TextStyle(
                  fontFamily: 'SF Mono',
                  fontFamilyFallback: ['Menlo', 'monospace'],
                  fontSize: 10,
                  color: DJIColors.secondary,
                ),
              ),
            ),
          ),
      ],
    );
  }
}
