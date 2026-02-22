import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

/// DJI Fly-inspired design system for Physical MCP.
///
/// Dark-first, glassmorphism-heavy, with precise color and typography
/// choices matching the DJI Fly app aesthetic.
class DJIColors {
  DJIColors._();

  // ── Backgrounds ──────────────────────────────────────────────
  static const Color background = Color(0xFF0A0A0F);
  static const Color surface = Color(0xFF141420);
  static const Color surfaceElevated = Color(0xFF1C1C2E);
  static const Color surfaceOverlay = Color(0xCC141420); // 80% opacity

  // ── Accent ───────────────────────────────────────────────────
  static const Color primary = Color(0xFF0971CE); // DJI Blue
  static const Color primaryLight = Color(0xFF3D9AE8);
  static const Color primaryDark = Color(0xFF065BA3);
  static const Color secondary = Color(0xFF00D4AA); // Teal / online
  static const Color secondaryDark = Color(0xFF00A888);

  // ── Semantic ─────────────────────────────────────────────────
  static const Color danger = Color(0xFFFF4757);
  static const Color dangerDark = Color(0xFFCC3945);
  static const Color warning = Color(0xFFFFA502);
  static const Color warningDark = Color(0xFFCC8401);
  static const Color success = Color(0xFF00D4AA);
  static const Color info = Color(0xFF0971CE);

  // ── Text ─────────────────────────────────────────────────────
  static const Color textPrimary = Color(0xF2FFFFFF); // 95% white
  static const Color textSecondary = Color(0x8CFFFFFF); // 55% white
  static const Color textTertiary = Color(0x4DFFFFFF); // 30% white
  static const Color textDisabled = Color(0x33FFFFFF); // 20% white

  // ── Borders & Dividers ───────────────────────────────────────
  static const Color border = Color(0x14FFFFFF); // 8% white
  static const Color borderLight = Color(0x0AFFFFFF); // 4% white
  static const Color divider = Color(0x14FFFFFF);

  // ── Priority colors ──────────────────────────────────────────
  static const Color priorityLow = Color(0xFF0971CE);
  static const Color priorityMedium = Color(0xFFFFA502);
  static const Color priorityHigh = Color(0xFFFF4757);
  static const Color priorityCritical = Color(0xFF9B59B6);

  /// Get priority color by name.
  static Color forPriority(String priority) {
    switch (priority.toLowerCase()) {
      case 'low':
        return priorityLow;
      case 'medium':
        return priorityMedium;
      case 'high':
        return priorityHigh;
      case 'critical':
        return priorityCritical;
      default:
        return priorityMedium;
    }
  }
}

/// DJI-inspired border radius constants.
class DJIRadius {
  DJIRadius._();

  static const double xs = 6.0;
  static const double sm = 8.0;
  static const double md = 12.0;
  static const double lg = 16.0;
  static const double xl = 20.0;
  static const double pill = 24.0;
  static const double round = 100.0;

  static BorderRadius get cardRadius => BorderRadius.circular(md);
  static BorderRadius get buttonRadius => BorderRadius.circular(sm);
  static BorderRadius get pillRadius => BorderRadius.circular(pill);
  static BorderRadius get chipRadius => BorderRadius.circular(round);
}

/// DJI-inspired spacing constants.
class DJISpacing {
  DJISpacing._();

  static const double xs = 4.0;
  static const double sm = 8.0;
  static const double md = 12.0;
  static const double lg = 16.0;
  static const double xl = 20.0;
  static const double xxl = 24.0;
  static const double xxxl = 32.0;
  static const double huge = 48.0;
}

/// DJI-inspired shadows and effects.
class DJIEffects {
  DJIEffects._();

  static const double glassBlur = 6.0;
  static const double glassBlurHeavy = 12.0;

  static List<BoxShadow> get cardShadow => [
        BoxShadow(
          color: Colors.black.withValues(alpha: 0.3),
          blurRadius: 12,
          offset: const Offset(0, 4),
        ),
        BoxShadow(
          color: Colors.black.withValues(alpha: 0.1),
          blurRadius: 24,
          offset: const Offset(0, 8),
        ),
      ];

  static List<BoxShadow> get elevatedShadow => [
        BoxShadow(
          color: Colors.black.withValues(alpha: 0.4),
          blurRadius: 20,
          offset: const Offset(0, 8),
        ),
      ];

  static List<BoxShadow> glowShadow(Color color) => [
        BoxShadow(
          color: color.withValues(alpha: 0.3),
          blurRadius: 12,
          spreadRadius: 2,
        ),
      ];
}

/// Build the complete DJI-styled Material ThemeData.
class DJITheme {
  DJITheme._();

  static ThemeData get dark {
    return ThemeData(
      useMaterial3: true,
      brightness: Brightness.dark,

      // ── Colors ────────────────────────────────────────────
      colorScheme: const ColorScheme.dark(
        primary: DJIColors.primary,
        onPrimary: Colors.white,
        secondary: DJIColors.secondary,
        onSecondary: Colors.black,
        surface: DJIColors.surface,
        onSurface: DJIColors.textPrimary,
        error: DJIColors.danger,
        onError: Colors.white,
      ),
      scaffoldBackgroundColor: DJIColors.background,
      canvasColor: DJIColors.background,

      // ── AppBar ────────────────────────────────────────────
      appBarTheme: const AppBarTheme(
        backgroundColor: Colors.transparent,
        elevation: 0,
        scrolledUnderElevation: 0,
        centerTitle: true,
        systemOverlayStyle: SystemUiOverlayStyle.light,
        titleTextStyle: TextStyle(
          color: DJIColors.textPrimary,
          fontSize: 18,
          fontWeight: FontWeight.w600,
          letterSpacing: -0.02 * 18,
        ),
        iconTheme: IconThemeData(color: DJIColors.textPrimary, size: 22),
      ),

      // ── Bottom Nav ────────────────────────────────────────
      bottomNavigationBarTheme: const BottomNavigationBarThemeData(
        backgroundColor: DJIColors.surface,
        selectedItemColor: DJIColors.primary,
        unselectedItemColor: DJIColors.textTertiary,
        type: BottomNavigationBarType.fixed,
        elevation: 0,
        selectedLabelStyle: TextStyle(
          fontSize: 11,
          fontWeight: FontWeight.w600,
          letterSpacing: 0.2,
        ),
        unselectedLabelStyle: TextStyle(
          fontSize: 11,
          fontWeight: FontWeight.w500,
          letterSpacing: 0.2,
        ),
      ),

      // ── NavigationBar (Material 3) ────────────────────────
      navigationBarTheme: NavigationBarThemeData(
        backgroundColor: DJIColors.surface,
        indicatorColor: DJIColors.primary.withValues(alpha: 0.15),
        surfaceTintColor: Colors.transparent,
        elevation: 0,
        height: 64,
        labelTextStyle: WidgetStateProperty.resolveWith((states) {
          if (states.contains(WidgetState.selected)) {
            return const TextStyle(
              fontSize: 11,
              fontWeight: FontWeight.w600,
              color: DJIColors.primary,
              letterSpacing: 0.2,
            );
          }
          return const TextStyle(
            fontSize: 11,
            fontWeight: FontWeight.w500,
            color: DJIColors.textTertiary,
            letterSpacing: 0.2,
          );
        }),
        iconTheme: WidgetStateProperty.resolveWith((states) {
          if (states.contains(WidgetState.selected)) {
            return const IconThemeData(
              color: DJIColors.primary,
              size: 22,
            );
          }
          return const IconThemeData(
            color: DJIColors.textTertiary,
            size: 22,
          );
        }),
      ),

      // ── Cards ─────────────────────────────────────────────
      cardTheme: CardThemeData(
        color: DJIColors.surface,
        elevation: 0,
        shape: RoundedRectangleBorder(
          borderRadius: DJIRadius.cardRadius,
          side: const BorderSide(color: DJIColors.border, width: 1),
        ),
        margin: EdgeInsets.zero,
      ),

      // ── Buttons ───────────────────────────────────────────
      elevatedButtonTheme: ElevatedButtonThemeData(
        style: ElevatedButton.styleFrom(
          backgroundColor: DJIColors.primary,
          foregroundColor: Colors.white,
          elevation: 0,
          padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 14),
          shape: RoundedRectangleBorder(
            borderRadius: DJIRadius.buttonRadius,
          ),
          textStyle: const TextStyle(
            fontSize: 15,
            fontWeight: FontWeight.w600,
            letterSpacing: -0.02 * 15,
          ),
        ),
      ),
      outlinedButtonTheme: OutlinedButtonThemeData(
        style: OutlinedButton.styleFrom(
          foregroundColor: DJIColors.textPrimary,
          side: const BorderSide(color: DJIColors.border),
          padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 14),
          shape: RoundedRectangleBorder(
            borderRadius: DJIRadius.buttonRadius,
          ),
          textStyle: const TextStyle(
            fontSize: 15,
            fontWeight: FontWeight.w600,
          ),
        ),
      ),
      textButtonTheme: TextButtonThemeData(
        style: TextButton.styleFrom(
          foregroundColor: DJIColors.primary,
          textStyle: const TextStyle(
            fontSize: 15,
            fontWeight: FontWeight.w600,
          ),
        ),
      ),

      // ── FAB ───────────────────────────────────────────────
      floatingActionButtonTheme: const FloatingActionButtonThemeData(
        backgroundColor: DJIColors.primary,
        foregroundColor: Colors.white,
        elevation: 4,
        shape: CircleBorder(),
      ),

      // ── Inputs ────────────────────────────────────────────
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: DJIColors.surfaceElevated,
        contentPadding:
            const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
        border: OutlineInputBorder(
          borderRadius: DJIRadius.buttonRadius,
          borderSide: const BorderSide(color: DJIColors.border),
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: DJIRadius.buttonRadius,
          borderSide: const BorderSide(color: DJIColors.border),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: DJIRadius.buttonRadius,
          borderSide: const BorderSide(color: DJIColors.primary, width: 1.5),
        ),
        errorBorder: OutlineInputBorder(
          borderRadius: DJIRadius.buttonRadius,
          borderSide: const BorderSide(color: DJIColors.danger),
        ),
        labelStyle: const TextStyle(
          color: DJIColors.textSecondary,
          fontSize: 14,
        ),
        hintStyle: const TextStyle(
          color: DJIColors.textTertiary,
          fontSize: 14,
        ),
      ),

      // ── Switch / Toggle ───────────────────────────────────
      switchTheme: SwitchThemeData(
        thumbColor: WidgetStateProperty.resolveWith((states) {
          if (states.contains(WidgetState.selected)) {
            return Colors.white;
          }
          return DJIColors.textTertiary;
        }),
        trackColor: WidgetStateProperty.resolveWith((states) {
          if (states.contains(WidgetState.selected)) {
            return DJIColors.primary;
          }
          return DJIColors.surfaceElevated;
        }),
      ),

      // ── Chips ─────────────────────────────────────────────
      chipTheme: ChipThemeData(
        backgroundColor: DJIColors.surfaceElevated,
        selectedColor: DJIColors.primary.withValues(alpha: 0.2),
        labelStyle: const TextStyle(
          fontSize: 12,
          fontWeight: FontWeight.w500,
          color: DJIColors.textSecondary,
        ),
        side: const BorderSide(color: DJIColors.border),
        shape: RoundedRectangleBorder(
          borderRadius: DJIRadius.chipRadius,
        ),
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
      ),

      // ── Dialogs ───────────────────────────────────────────
      dialogTheme: DialogThemeData(
        backgroundColor: DJIColors.surfaceElevated,
        shape: RoundedRectangleBorder(
          borderRadius: DJIRadius.cardRadius,
        ),
        titleTextStyle: const TextStyle(
          color: DJIColors.textPrimary,
          fontSize: 20,
          fontWeight: FontWeight.w600,
        ),
      ),

      // ── Snackbar ──────────────────────────────────────────
      snackBarTheme: SnackBarThemeData(
        backgroundColor: DJIColors.surfaceElevated,
        contentTextStyle: const TextStyle(
          color: DJIColors.textPrimary,
          fontSize: 14,
        ),
        shape: RoundedRectangleBorder(
          borderRadius: DJIRadius.buttonRadius,
        ),
        behavior: SnackBarBehavior.floating,
      ),

      // ── Divider ───────────────────────────────────────────
      dividerTheme: const DividerThemeData(
        color: DJIColors.divider,
        thickness: 1,
        space: 1,
      ),

      // ── Text ──────────────────────────────────────────────
      textTheme: const TextTheme(
        // Screen titles
        headlineLarge: TextStyle(
          fontSize: 28,
          fontWeight: FontWeight.w600,
          color: DJIColors.textPrimary,
          letterSpacing: -0.02 * 28,
        ),
        // Section headers
        headlineMedium: TextStyle(
          fontSize: 22,
          fontWeight: FontWeight.w600,
          color: DJIColors.textPrimary,
          letterSpacing: -0.02 * 22,
        ),
        // Card titles
        headlineSmall: TextStyle(
          fontSize: 20,
          fontWeight: FontWeight.w600,
          color: DJIColors.textPrimary,
          letterSpacing: -0.02 * 20,
        ),
        // List item titles
        titleLarge: TextStyle(
          fontSize: 17,
          fontWeight: FontWeight.w600,
          color: DJIColors.textPrimary,
          letterSpacing: -0.02 * 17,
        ),
        titleMedium: TextStyle(
          fontSize: 15,
          fontWeight: FontWeight.w600,
          color: DJIColors.textPrimary,
        ),
        titleSmall: TextStyle(
          fontSize: 13,
          fontWeight: FontWeight.w600,
          color: DJIColors.textSecondary,
        ),
        // Body text
        bodyLarge: TextStyle(
          fontSize: 15,
          fontWeight: FontWeight.w400,
          color: DJIColors.textPrimary,
        ),
        bodyMedium: TextStyle(
          fontSize: 14,
          fontWeight: FontWeight.w400,
          color: DJIColors.textSecondary,
        ),
        bodySmall: TextStyle(
          fontSize: 12,
          fontWeight: FontWeight.w400,
          color: DJIColors.textTertiary,
        ),
        // Labels (small)
        labelLarge: TextStyle(
          fontSize: 13,
          fontWeight: FontWeight.w600,
          color: DJIColors.textPrimary,
          letterSpacing: 0.3,
        ),
        labelMedium: TextStyle(
          fontSize: 11,
          fontWeight: FontWeight.w500,
          color: DJIColors.textSecondary,
          letterSpacing: 0.3,
        ),
        labelSmall: TextStyle(
          fontSize: 10,
          fontWeight: FontWeight.w500,
          color: DJIColors.textTertiary,
          letterSpacing: 0.4,
        ),
      ),
    );
  }

  /// HUD overlay text style (monospace numbers, like DJI telemetry).
  static TextStyle get hudText => const TextStyle(
        fontFamily: 'SF Mono',
        fontFamilyFallback: ['Menlo', 'Roboto Mono', 'monospace'],
        fontSize: 13,
        fontWeight: FontWeight.w500,
        color: DJIColors.textPrimary,
        letterSpacing: 0.5,
      );

  /// Large HUD number style (altitude, speed, etc.).
  static TextStyle get hudNumber => const TextStyle(
        fontFamily: 'SF Mono',
        fontFamilyFallback: ['Menlo', 'Roboto Mono', 'monospace'],
        fontSize: 20,
        fontWeight: FontWeight.w600,
        color: Colors.white,
        letterSpacing: 0.5,
      );
}
