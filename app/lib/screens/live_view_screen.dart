import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../models/camera.dart';
import '../services/api_client.dart';
import '../theme/dji_theme.dart';
import '../widgets/camera_feed.dart';
import '../widgets/hud_overlay.dart';

/// Full-screen live camera view with DJI-style HUD.
///
/// The hero screen of the app. Camera feed fills the entire screen,
/// with a semi-transparent HUD showing camera info and AI scene data.
/// Tap to toggle overlays. Pinch to zoom.
class LiveViewScreen extends StatefulWidget {
  final Camera camera;
  final ApiClient apiClient;

  const LiveViewScreen({
    super.key,
    required this.camera,
    required this.apiClient,
  });

  @override
  State<LiveViewScreen> createState() => _LiveViewScreenState();
}

class _LiveViewScreenState extends State<LiveViewScreen> {
  bool _hudVisible = true;
  final bool _isConnected = true;
  SceneState? _currentScene;
  Timer? _sceneTimer;
  double _scale = 1.0;
  double _baseScale = 1.0;

  @override
  void initState() {
    super.initState();
    _currentScene = widget.camera.scene;

    // Immersive mode
    SystemChrome.setEnabledSystemUIMode(SystemUiMode.immersiveSticky);

    // Poll scene state every 3 seconds
    _sceneTimer = Timer.periodic(const Duration(seconds: 3), (_) async {
      try {
        final scene = await widget.apiClient.getScene();
        if (mounted) {
          setState(() => _currentScene = scene);
        }
      } catch (_) {
        // Silently continue — scene will update when available
      }
    });
  }

  @override
  void dispose() {
    _sceneTimer?.cancel();
    SystemChrome.setEnabledSystemUIMode(SystemUiMode.edgeToEdge);
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.black,
      body: GestureDetector(
        // Tap to toggle HUD
        onTap: () => setState(() => _hudVisible = !_hudVisible),

        // Double tap to toggle HUD
        onDoubleTap: () => setState(() => _hudVisible = !_hudVisible),

        // Pinch to zoom
        onScaleStart: (details) => _baseScale = _scale,
        onScaleUpdate: (details) {
          setState(() {
            _scale = (_baseScale * details.scale).clamp(1.0, 3.0);
          });
        },

        child: Stack(
          fit: StackFit.expand,
          children: [
            // Camera feed — fills entire screen
            Transform.scale(
              scale: _scale,
              child: CameraFeed(
                streamUrl: widget.apiClient.getStreamUrl(
                  cameraId: widget.camera.id,
                ),
                headers: widget.apiClient.config.headers,
                fit: BoxFit.cover,
                showFps: true,
              ),
            ),

            // DJI-style HUD overlay
            HudOverlay(
              cameraName: widget.camera.name,
              isConnected: _isConnected,
              scene: _currentScene,
              visible: _hudVisible,
              onBack: () => Navigator.of(context).pop(),
            ),

            // Zoom indicator
            if (_scale > 1.05)
              Positioned(
                top: MediaQuery.of(context).padding.top + 60,
                right: DJISpacing.lg,
                child: AnimatedOpacity(
                  opacity: _scale > 1.05 ? 1.0 : 0.0,
                  duration: const Duration(milliseconds: 200),
                  child: Container(
                    padding: const EdgeInsets.symmetric(
                      horizontal: 10,
                      vertical: 4,
                    ),
                    decoration: BoxDecoration(
                      color: Colors.black.withValues(alpha: 0.6),
                      borderRadius: BorderRadius.circular(DJIRadius.pill),
                    ),
                    child: Text(
                      '${_scale.toStringAsFixed(1)}x',
                      style: DJITheme.hudText.copyWith(
                        color: DJIColors.primary,
                        fontSize: 12,
                      ),
                    ),
                  ),
                ),
              ),
          ],
        ),
      ),
    );
  }
}
