import 'dart:io' show Platform;

import 'package:flutter/material.dart';
import 'package:flutter_animate/flutter_animate.dart';

import '../models/camera.dart';
import '../theme/dji_theme.dart';
import '../widgets/camera_feed.dart';
import '../widgets/glassmorphic_card.dart';
import '../widgets/scene_summary.dart';
import '../widgets/shimmer_loading.dart';
import '../widgets/status_dot.dart';

/// Dashboard home screen — 2x2 camera grid (like Wyze home screen).
///
/// Each tile shows a live camera feed with name, status, and scene summary.
/// Tap to enter full Live View.
class DashboardScreen extends StatelessWidget {
  final List<Camera> cameras;
  final bool isLoading;
  final String serverBaseUrl;
  final Map<String, String>? headers;
  final void Function(Camera camera) onCameraTap;
  final VoidCallback onAddCamera;
  final Future<void> Function()? onRefresh;

  const DashboardScreen({
    super.key,
    required this.cameras,
    this.isLoading = false,
    required this.serverBaseUrl,
    this.headers,
    required this.onCameraTap,
    required this.onAddCamera,
    this.onRefresh,
  });

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: DJIColors.background,
      body: SafeArea(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // Header
            Padding(
              padding: const EdgeInsets.all(DJISpacing.xl),
              child: Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Text(
                        'My Cameras',
                        style: TextStyle(
                          color: DJIColors.textPrimary,
                          fontSize: 28,
                          fontWeight: FontWeight.w600,
                          letterSpacing: -0.5,
                        ),
                      ),
                      const SizedBox(height: 2),
                      Text(
                        '${cameras.length} camera${cameras.length != 1 ? 's' : ''} online',
                        style: const TextStyle(
                          color: DJIColors.textSecondary,
                          fontSize: 14,
                        ),
                      ),
                    ],
                  ),
                  // Connection status
                  Container(
                    padding: const EdgeInsets.symmetric(
                      horizontal: 12,
                      vertical: 6,
                    ),
                    decoration: BoxDecoration(
                      color: DJIColors.secondary.withValues(alpha: 0.1),
                      borderRadius: BorderRadius.circular(DJIRadius.round),
                      border: Border.all(
                        color: DJIColors.secondary.withValues(alpha: 0.3),
                      ),
                    ),
                    child: Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        const StatusDot(isConnected: true, size: 6),
                        const SizedBox(width: 6),
                        const Text(
                          'Connected',
                          style: TextStyle(
                            color: DJIColors.secondary,
                            fontSize: 12,
                            fontWeight: FontWeight.w600,
                          ),
                        ),
                      ],
                    ),
                  ),
                ],
              ),
            ),

            // Camera grid
            Expanded(
              child: isLoading
                  ? _buildLoadingGrid()
                  : cameras.isEmpty
                      ? _buildEmptyState()
                      : RefreshIndicator(
                          onRefresh: onRefresh ?? () async {},
                          color: DJIColors.primary,
                          backgroundColor: DJIColors.surface,
                          child: _buildCameraGrid(),
                        ),
            ),
          ],
        ),
      ),
      floatingActionButton: FloatingActionButton(
        onPressed: onAddCamera,
        child: const Icon(Icons.add_rounded),
      ),
    );
  }

  Widget _buildCameraGrid() {
    return GridView.builder(
      padding: const EdgeInsets.symmetric(horizontal: DJISpacing.xl),
      gridDelegate: const SliverGridDelegateWithFixedCrossAxisCount(
        crossAxisCount: 2,
        childAspectRatio: 0.85,
        crossAxisSpacing: DJISpacing.md,
        mainAxisSpacing: DJISpacing.md,
      ),
      itemCount: cameras.length,
      itemBuilder: (context, index) {
        final camera = cameras[index];
        return _CameraTile(
          camera: camera,
          streamUrl: '$serverBaseUrl/stream?camera_id=${camera.id}',
          headers: headers,
          onTap: () => onCameraTap(camera),
        )
            .animate()
            .fadeIn(
              delay: Duration(milliseconds: 100 * index),
              duration: 400.ms,
            )
            .scale(
              begin: const Offset(0.95, 0.95),
              end: const Offset(1.0, 1.0),
              delay: Duration(milliseconds: 100 * index),
              duration: 400.ms,
            );
      },
    );
  }

  Widget _buildLoadingGrid() {
    return GridView.builder(
      padding: const EdgeInsets.symmetric(horizontal: DJISpacing.xl),
      gridDelegate: const SliverGridDelegateWithFixedCrossAxisCount(
        crossAxisCount: 2,
        childAspectRatio: 0.85,
        crossAxisSpacing: DJISpacing.md,
        mainAxisSpacing: DJISpacing.md,
      ),
      itemCount: 4,
      itemBuilder: (_, _) => const CameraTileSkeleton(),
    );
  }

  Widget _buildEmptyState() {
    return Center(
      child: Builder(
        builder: (context) => Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(
              Icons.videocam_off_rounded,
              size: 64,
              color: DJIColors.textTertiary,
            ),
            const SizedBox(height: DJISpacing.lg),
            const Text(
              'No cameras found',
              style: TextStyle(
                color: DJIColors.textSecondary,
                fontSize: 18,
                fontWeight: FontWeight.w600,
              ),
            ),
            const SizedBox(height: DJISpacing.sm),
            const Text(
              'Your server is connected but no cameras\nwere detected. Connect a USB camera\nand pull down to refresh.',
              textAlign: TextAlign.center,
              style: TextStyle(
                color: DJIColors.textTertiary,
                fontSize: 14,
                height: 1.5,
              ),
            ),
            if (Platform.isMacOS) ...[
              const SizedBox(height: DJISpacing.lg),
              TextButton.icon(
                icon: const Icon(Icons.security_rounded, size: 16),
                label: const Text('Camera permission issue?'),
                style: TextButton.styleFrom(
                  foregroundColor: DJIColors.primary,
                ),
                onPressed: () {
                  showDialog(
                    context: context,
                    builder: (_) => AlertDialog(
                      backgroundColor: DJIColors.surface,
                      title: const Text(
                        'Camera Permission',
                        style: TextStyle(color: DJIColors.textPrimary),
                      ),
                      content: const Text(
                        'If your camera is connected but not detected:\n\n'
                        '1. Open System Settings \u2192 Privacy & Security \u2192 Camera\n'
                        '2. Ensure "Physical MCP" is listed and enabled\n'
                        '3. If not listed, try running this in Terminal:\n'
                        '   tccutil reset Camera\n'
                        '4. Then restart the app\n\n'
                        'Some USB cameras take a few seconds to initialize.\n'
                        'Pull down on the camera grid to retry.',
                        style: TextStyle(
                          color: DJIColors.textSecondary,
                          height: 1.5,
                        ),
                      ),
                      actions: [
                        TextButton(
                          onPressed: () => Navigator.of(context).pop(),
                          child: const Text('Got it'),
                        ),
                      ],
                    ),
                  );
                },
              ),
            ],
          ],
        ),
      ),
    );
  }
}

class _CameraTile extends StatelessWidget {
  final Camera camera;
  final String streamUrl;
  final Map<String, String>? headers;
  final VoidCallback onTap;

  const _CameraTile({
    required this.camera,
    required this.streamUrl,
    this.headers,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return GlassmorphicCard(
      onTap: onTap,
      padding: EdgeInsets.zero,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // Live feed
          Expanded(
            child: ClipRRect(
              borderRadius: const BorderRadius.vertical(
                top: Radius.circular(12),
              ),
              child: Stack(
                fit: StackFit.expand,
                children: [
                  CameraFeed(
                    streamUrl: streamUrl,
                    headers: headers,
                    fit: BoxFit.cover,
                  ),

                  // Gradient overlay at bottom
                  Positioned(
                    bottom: 0,
                    left: 0,
                    right: 0,
                    height: 40,
                    child: Container(
                      decoration: BoxDecoration(
                        gradient: LinearGradient(
                          begin: Alignment.bottomCenter,
                          end: Alignment.topCenter,
                          colors: [
                            Colors.black.withValues(alpha: 0.5),
                            Colors.transparent,
                          ],
                        ),
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ),

          // Info bar
          Padding(
            padding: const EdgeInsets.all(DJISpacing.md),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    StatusDot(
                      isConnected: camera.enabled,
                      size: 6,
                    ),
                    const SizedBox(width: DJISpacing.sm),
                    Expanded(
                      child: Text(
                        camera.name,
                        style: const TextStyle(
                          color: DJIColors.textPrimary,
                          fontSize: 14,
                          fontWeight: FontWeight.w600,
                        ),
                        overflow: TextOverflow.ellipsis,
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 4),
                SceneSummary(
                  scene: camera.scene,
                  maxLines: 1,
                  fontSize: 11,
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
