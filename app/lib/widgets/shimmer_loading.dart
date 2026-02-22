import 'package:flutter/material.dart';
import 'package:shimmer/shimmer.dart';

import '../theme/dji_theme.dart';

/// Skeleton loading placeholder with DJI-themed shimmer effect.
class ShimmerLoading extends StatelessWidget {
  final double? width;
  final double? height;
  final double borderRadius;
  final Widget? child;

  const ShimmerLoading({
    super.key,
    this.width,
    this.height,
    this.borderRadius = 12.0,
    this.child,
  });

  @override
  Widget build(BuildContext context) {
    return Shimmer.fromColors(
      baseColor: DJIColors.surfaceElevated,
      highlightColor: DJIColors.surface,
      child: child ??
          Container(
            width: width,
            height: height,
            decoration: BoxDecoration(
              color: DJIColors.surfaceElevated,
              borderRadius: BorderRadius.circular(borderRadius),
            ),
          ),
    );
  }
}

/// Camera tile skeleton placeholder.
class CameraTileSkeleton extends StatelessWidget {
  const CameraTileSkeleton({super.key});

  @override
  Widget build(BuildContext context) {
    return const ShimmerLoading(
      borderRadius: 12,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // Video area
          Expanded(
            child: ShimmerLoading(borderRadius: 12),
          ),
          SizedBox(height: 8),
          // Title
          ShimmerLoading(width: 120, height: 14, borderRadius: 4),
          SizedBox(height: 4),
          // Subtitle
          ShimmerLoading(width: 80, height: 10, borderRadius: 4),
        ],
      ),
    );
  }
}
