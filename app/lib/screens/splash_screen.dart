import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_animate/flutter_animate.dart';

import '../theme/dji_theme.dart';
import '../widgets/app_logo.dart';

/// Splash screen with logo animation and auto-discovery.
///
/// Shows the Physical MCP logo fading in, then "Searching for cameras..."
/// with a subtle pulse. Auto-navigates when backend is found.
class SplashScreen extends StatefulWidget {
  final Future<bool> Function() onCheckConnection;
  final VoidCallback onConnected;
  final VoidCallback onNotFound;

  const SplashScreen({
    super.key,
    required this.onCheckConnection,
    required this.onConnected,
    required this.onNotFound,
  });

  @override
  State<SplashScreen> createState() => _SplashScreenState();
}

class _SplashScreenState extends State<SplashScreen> {
  String _status = 'Initializing...';
  bool _searching = false;

  @override
  void initState() {
    super.initState();
    _startDiscovery();
  }

  Future<void> _startDiscovery() async {
    await Future.delayed(const Duration(milliseconds: 1200));

    if (!mounted) return;
    setState(() {
      _status = 'Searching for cameras on your network...';
      _searching = true;
    });

    // Try to discover backend
    final found = await widget.onCheckConnection();

    if (!mounted) return;

    if (found) {
      setState(() => _status = 'Connected!');
      await Future.delayed(const Duration(milliseconds: 500));
      if (mounted) widget.onConnected();
    } else {
      setState(() {
        _status = 'No cameras found';
        _searching = false;
      });
      await Future.delayed(const Duration(milliseconds: 800));
      if (mounted) widget.onNotFound();
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: DJIColors.background,
      body: Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            // Logo
            const AppLogo(size: 88)
                .animate()
                .fadeIn(duration: 600.ms, curve: Curves.easeOut)
                .scale(
                  begin: const Offset(0.8, 0.8),
                  end: const Offset(1.0, 1.0),
                  duration: 600.ms,
                  curve: Curves.easeOut,
                ),

            const SizedBox(height: DJISpacing.xxl),

            // App name
            const Text(
              'Physical MCP',
              style: TextStyle(
                color: DJIColors.textPrimary,
                fontSize: 28,
                fontWeight: FontWeight.w600,
                letterSpacing: -0.5,
              ),
            )
                .animate()
                .fadeIn(delay: 300.ms, duration: 500.ms),

            const SizedBox(height: DJISpacing.sm),

            const Text(
              'AI Vision for Your World',
              style: TextStyle(
                color: DJIColors.textSecondary,
                fontSize: 15,
              ),
            )
                .animate()
                .fadeIn(delay: 500.ms, duration: 500.ms),

            const SizedBox(height: DJISpacing.huge),

            // Status
            Text(
              _status,
              style: const TextStyle(
                color: DJIColors.textTertiary,
                fontSize: 13,
              ),
            )
                .animate()
                .fadeIn(delay: 800.ms, duration: 400.ms),

            const SizedBox(height: DJISpacing.lg),

            // Loading indicator
            if (_searching)
              SizedBox(
                width: 24,
                height: 24,
                child: const CircularProgressIndicator(
                  color: DJIColors.primary,
                  strokeWidth: 2,
                ),
              )
                  .animate(onPlay: (c) => c.repeat())
                  .fadeIn(duration: 300.ms),
          ],
        ),
      ),
    );
  }
}
