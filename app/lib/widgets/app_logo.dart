import 'package:flutter/material.dart';

import '../theme/dji_theme.dart';

/// Branded Physical MCP logo — camera lens / eye design.
///
/// Draws the same design used in the app icon: concentric rings in DJI Blue
/// on a dark background with a glowing center pupil.
class AppLogo extends StatelessWidget {
  final double size;

  const AppLogo({super.key, this.size = 80});

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: size,
      height: size,
      child: CustomPaint(
        size: Size(size, size),
        painter: _LogoPainter(),
      ),
    );
  }
}

class _LogoPainter extends CustomPainter {
  @override
  void paint(Canvas canvas, Size size) {
    final center = Offset(size.width / 2, size.height / 2);
    final maxR = size.width / 2;

    // Background rounded rect
    final bgPaint = Paint()..color = DJIColors.background;
    final bgRect = RRect.fromRectAndRadius(
      Rect.fromLTWH(0, 0, size.width, size.height),
      Radius.circular(size.width * 0.22),
    );
    canvas.drawRRect(bgRect, bgPaint);

    // Outer ring — DJI Blue
    final ringPaint = Paint()
      ..color = DJIColors.primary
      ..style = PaintingStyle.stroke
      ..strokeWidth = maxR * 0.14;
    canvas.drawCircle(center, maxR * 0.67, ringPaint);

    // Inner ring — subtle
    final innerRingPaint = Paint()
      ..color = DJIColors.primary.withValues(alpha: 0.4)
      ..style = PaintingStyle.stroke
      ..strokeWidth = maxR * 0.05;
    canvas.drawCircle(center, maxR * 0.42, innerRingPaint);

    // Center glow
    final glowPaint = Paint()
      ..shader = RadialGradient(
        colors: [
          DJIColors.primary.withValues(alpha: 0.6),
          DJIColors.primary.withValues(alpha: 0.0),
        ],
      ).createShader(
        Rect.fromCircle(center: center, radius: maxR * 0.3),
      );
    canvas.drawCircle(center, maxR * 0.3, glowPaint);

    // Center pupil — solid DJI Blue
    final pupilPaint = Paint()..color = DJIColors.primary;
    canvas.drawCircle(center, maxR * 0.15, pupilPaint);

    // Bright inner dot
    final dotPaint = Paint()..color = DJIColors.primaryLight;
    canvas.drawCircle(center, maxR * 0.06, dotPaint);

    // Highlight reflection
    final highlightPaint = Paint()
      ..color = Colors.white.withValues(alpha: 0.3);
    canvas.drawCircle(
      Offset(center.dx + maxR * 0.08, center.dy - maxR * 0.12),
      maxR * 0.04,
      highlightPaint,
    );
  }

  @override
  bool shouldRepaint(covariant CustomPainter oldDelegate) => false;
}
