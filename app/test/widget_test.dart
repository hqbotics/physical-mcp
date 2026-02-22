import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:physical_mcp_app/theme/dji_theme.dart';

void main() {
  test('DJI theme has correct background color', () {
    expect(DJIColors.background, const Color(0xFF0A0A0F));
  });

  test('DJI theme has correct primary color', () {
    expect(DJIColors.primary, const Color(0xFF0971CE));
  });

  test('DJI theme dark mode has correct scaffold color', () {
    final theme = DJITheme.dark;
    expect(theme.scaffoldBackgroundColor, DJIColors.background);
    expect(theme.brightness, Brightness.dark);
  });

  test('DJI priority colors are assigned correctly', () {
    expect(DJIColors.forPriority('low'), DJIColors.priorityLow);
    expect(DJIColors.forPriority('medium'), DJIColors.priorityMedium);
    expect(DJIColors.forPriority('high'), DJIColors.priorityHigh);
    expect(DJIColors.forPriority('critical'), DJIColors.priorityCritical);
    // Unknown defaults to medium
    expect(DJIColors.forPriority('unknown'), DJIColors.priorityMedium);
  });
}
