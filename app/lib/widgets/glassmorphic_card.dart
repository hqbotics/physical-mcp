import 'dart:ui';

import 'package:flutter/material.dart';

import '../theme/dji_theme.dart';

/// DJI-style glassmorphism card with backdrop blur and subtle border.
///
/// The signature visual component of the app — used for camera tiles,
/// alert cards, settings groups, and HUD panels.
class GlassmorphicCard extends StatelessWidget {
  final Widget child;
  final EdgeInsetsGeometry? padding;
  final EdgeInsetsGeometry? margin;
  final double? width;
  final double? height;
  final double borderRadius;
  final double blurAmount;
  final Color? backgroundColor;
  final Color? borderColor;
  final VoidCallback? onTap;
  final VoidCallback? onLongPress;
  final bool elevated;

  const GlassmorphicCard({
    super.key,
    required this.child,
    this.padding,
    this.margin,
    this.width,
    this.height,
    this.borderRadius = 12.0,
    this.blurAmount = 6.0,
    this.backgroundColor,
    this.borderColor,
    this.onTap,
    this.onLongPress,
    this.elevated = false,
  });

  @override
  Widget build(BuildContext context) {
    final bgColor =
        backgroundColor ?? DJIColors.surface.withValues(alpha: 0.8);
    final border = borderColor ?? DJIColors.border;

    Widget card = ClipRRect(
      borderRadius: BorderRadius.circular(borderRadius),
      child: BackdropFilter(
        filter: ImageFilter.blur(
          sigmaX: blurAmount,
          sigmaY: blurAmount,
        ),
        child: Container(
          width: width,
          height: height,
          decoration: BoxDecoration(
            color: bgColor,
            borderRadius: BorderRadius.circular(borderRadius),
            border: Border.all(
              color: border,
              width: 1,
            ),
            boxShadow: elevated ? DJIEffects.cardShadow : null,
          ),
          padding: padding ?? const EdgeInsets.all(DJISpacing.lg),
          child: child,
        ),
      ),
    );

    if (onTap != null || onLongPress != null) {
      card = GestureDetector(
        onTap: onTap,
        onLongPress: onLongPress,
        child: card,
      );
    }

    if (margin != null) {
      card = Padding(padding: margin!, child: card);
    }

    return card;
  }
}

/// Compact glassmorphic pill for HUD overlays.
class GlassmorphicPill extends StatelessWidget {
  final Widget child;
  final EdgeInsetsGeometry? padding;
  final Color? backgroundColor;
  final VoidCallback? onTap;

  const GlassmorphicPill({
    super.key,
    required this.child,
    this.padding,
    this.backgroundColor,
    this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return GlassmorphicCard(
      borderRadius: DJIRadius.pill,
      padding: padding ??
          const EdgeInsets.symmetric(
            horizontal: DJISpacing.md,
            vertical: DJISpacing.xs,
          ),
      backgroundColor:
          backgroundColor ?? Colors.black.withValues(alpha: 0.55),
      blurAmount: DJIEffects.glassBlurHeavy,
      onTap: onTap,
      child: child,
    );
  }
}
