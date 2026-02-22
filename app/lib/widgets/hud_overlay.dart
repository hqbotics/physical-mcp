import 'dart:ui';

import 'package:flutter/material.dart';

import '../models/camera.dart';
import '../theme/dji_theme.dart';
import 'glassmorphic_card.dart';
import 'status_dot.dart';

/// DJI Fly-style heads-up display overlay for the live camera view.
///
/// Shows camera info, scene summary, object pills on top of the feed.
/// Designed to look exactly like DJI Fly's viewfinder HUD.
class HudOverlay extends StatelessWidget {
  final String cameraName;
  final bool isConnected;
  final SceneState? scene;
  final VoidCallback? onBack;
  final bool visible;

  const HudOverlay({
    super.key,
    required this.cameraName,
    required this.isConnected,
    this.scene,
    this.onBack,
    this.visible = true,
  });

  @override
  Widget build(BuildContext context) {
    return AnimatedOpacity(
      opacity: visible ? 1.0 : 0.0,
      duration: const Duration(milliseconds: 200),
      child: IgnorePointer(
        ignoring: !visible,
        child: Stack(
          children: [
            // ── Top bar ──────────────────────────────────────
            Positioned(
              top: 0,
              left: 0,
              right: 0,
              child: _buildTopBar(context),
            ),

            // ── Bottom bar ───────────────────────────────────
            Positioned(
              bottom: 0,
              left: 0,
              right: 0,
              child: _buildBottomBar(context),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildTopBar(BuildContext context) {
    final safePadding = MediaQuery.of(context).padding.top;

    return ClipRect(
      child: BackdropFilter(
        filter: ImageFilter.blur(sigmaX: 8, sigmaY: 8),
        child: Container(
          padding: EdgeInsets.only(
            top: safePadding + DJISpacing.sm,
            left: DJISpacing.lg,
            right: DJISpacing.lg,
            bottom: DJISpacing.md,
          ),
          decoration: BoxDecoration(
            gradient: LinearGradient(
              begin: Alignment.topCenter,
              end: Alignment.bottomCenter,
              colors: [
                Colors.black.withValues(alpha: 0.6),
                Colors.transparent,
              ],
            ),
          ),
          child: Row(
            children: [
              // Back button
              if (onBack != null)
                GestureDetector(
                  onTap: onBack,
                  child: const Padding(
                    padding: EdgeInsets.only(right: DJISpacing.md),
                    child: Icon(
                      Icons.arrow_back_ios_rounded,
                      color: Colors.white,
                      size: 20,
                    ),
                  ),
                ),

              // Camera name
              Expanded(
                child: Text(
                  cameraName,
                  style: const TextStyle(
                    color: Colors.white,
                    fontSize: 16,
                    fontWeight: FontWeight.w600,
                    letterSpacing: -0.3,
                  ),
                  overflow: TextOverflow.ellipsis,
                ),
              ),

              // Connection status
              StatusDot(isConnected: isConnected, size: 8),
              const SizedBox(width: DJISpacing.sm),

              // People count
              if (scene?.peopleCount != null && scene!.peopleCount! > 0) ...[
                Icon(
                  Icons.person_rounded,
                  color: DJIColors.secondary,
                  size: 16,
                ),
                const SizedBox(width: 2),
                Text(
                  '${scene!.peopleCount}',
                  style: DJITheme.hudText.copyWith(
                    color: DJIColors.secondary,
                  ),
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildBottomBar(BuildContext context) {
    final safePadding = MediaQuery.of(context).padding.bottom;

    return ClipRect(
      child: BackdropFilter(
        filter: ImageFilter.blur(sigmaX: 8, sigmaY: 8),
        child: Container(
          padding: EdgeInsets.only(
            top: DJISpacing.md,
            left: DJISpacing.lg,
            right: DJISpacing.lg,
            bottom: safePadding + DJISpacing.md,
          ),
          decoration: BoxDecoration(
            gradient: LinearGradient(
              begin: Alignment.bottomCenter,
              end: Alignment.topCenter,
              colors: [
                Colors.black.withValues(alpha: 0.6),
                Colors.transparent,
              ],
            ),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            mainAxisSize: MainAxisSize.min,
            children: [
              // AI scene summary
              if (scene?.summary != null && scene!.summary.isNotEmpty)
                Text(
                  scene!.summary,
                  style: const TextStyle(
                    color: Colors.white,
                    fontSize: 14,
                    fontWeight: FontWeight.w400,
                    height: 1.3,
                  ),
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                ),

              // Object pills
              if (scene?.objects != null && scene!.objects.isNotEmpty) ...[
                const SizedBox(height: DJISpacing.sm),
                Wrap(
                  spacing: DJISpacing.xs,
                  runSpacing: DJISpacing.xs,
                  children: scene!.objects.take(6).map((obj) {
                    return GlassmorphicPill(
                      padding: const EdgeInsets.symmetric(
                        horizontal: 10,
                        vertical: 4,
                      ),
                      child: Text(
                        obj,
                        style: const TextStyle(
                          color: Colors.white,
                          fontSize: 11,
                          fontWeight: FontWeight.w500,
                        ),
                      ),
                    );
                  }).toList(),
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }
}
