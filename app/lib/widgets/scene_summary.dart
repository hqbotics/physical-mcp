import 'package:flutter/material.dart';

import '../models/camera.dart';
import '../theme/dji_theme.dart';

/// Compact AI scene description shown on camera tiles.
class SceneSummary extends StatelessWidget {
  final SceneState? scene;
  final int maxLines;
  final double fontSize;

  const SceneSummary({
    super.key,
    this.scene,
    this.maxLines = 2,
    this.fontSize = 12,
  });

  @override
  Widget build(BuildContext context) {
    if (scene == null || scene!.summary.isEmpty) {
      return Text(
        'Analyzing...',
        style: TextStyle(
          color: DJIColors.textTertiary,
          fontSize: fontSize,
          fontStyle: FontStyle.italic,
        ),
      );
    }

    return Text(
      scene!.summary,
      style: TextStyle(
        color: DJIColors.textSecondary,
        fontSize: fontSize,
        height: 1.3,
      ),
      maxLines: maxLines,
      overflow: TextOverflow.ellipsis,
    );
  }
}
