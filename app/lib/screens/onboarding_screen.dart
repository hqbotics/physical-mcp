import 'package:flutter/material.dart';
import 'package:flutter_animate/flutter_animate.dart';

import '../theme/dji_theme.dart';
import '../widgets/app_logo.dart';

/// First-run onboarding — 3 pages introducing Physical MCP.
///
/// Shown only on first launch (controlled by SharedPreferences).
/// User taps "Get Started" to proceed to the normal splash/discovery flow.
class OnboardingScreen extends StatefulWidget {
  final VoidCallback onComplete;
  final bool isEmbedded;

  const OnboardingScreen({
    super.key,
    required this.onComplete,
    this.isEmbedded = false,
  });

  @override
  State<OnboardingScreen> createState() => _OnboardingScreenState();
}

class _OnboardingScreenState extends State<OnboardingScreen> {
  final PageController _pageController = PageController();
  int _currentPage = 0;

  @override
  void dispose() {
    _pageController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: DJIColors.background,
      body: SafeArea(
        child: Column(
          children: [
            // Skip button
            Align(
              alignment: Alignment.topRight,
              child: Padding(
                padding: const EdgeInsets.all(DJISpacing.lg),
                child: TextButton(
                  onPressed: widget.onComplete,
                  child: Text(
                    _currentPage == 2 ? '' : 'Skip',
                    style: const TextStyle(
                      color: DJIColors.textTertiary,
                      fontSize: 14,
                    ),
                  ),
                ),
              ),
            ),

            // Pages
            Expanded(
              child: PageView(
                controller: _pageController,
                onPageChanged: (i) => setState(() => _currentPage = i),
                children: [
                  _buildPage1(),
                  _buildPage2(),
                  _buildPage3(),
                ],
              ),
            ),

            // Page indicator dots
            Padding(
              padding: const EdgeInsets.only(bottom: DJISpacing.lg),
              child: Row(
                mainAxisAlignment: MainAxisAlignment.center,
                children: List.generate(3, (i) {
                  final isActive = i == _currentPage;
                  return AnimatedContainer(
                    duration: const Duration(milliseconds: 200),
                    margin: const EdgeInsets.symmetric(horizontal: 4),
                    width: isActive ? 24 : 8,
                    height: 8,
                    decoration: BoxDecoration(
                      color: isActive
                          ? DJIColors.primary
                          : DJIColors.textDisabled,
                      borderRadius: BorderRadius.circular(4),
                    ),
                  );
                }),
              ),
            ),

            // Bottom button
            Padding(
              padding: const EdgeInsets.fromLTRB(
                DJISpacing.xl,
                0,
                DJISpacing.xl,
                DJISpacing.xxxl,
              ),
              child: SizedBox(
                width: double.infinity,
                child: ElevatedButton(
                  onPressed: _currentPage == 2
                      ? widget.onComplete
                      : () {
                          _pageController.nextPage(
                            duration: const Duration(milliseconds: 300),
                            curve: Curves.easeInOut,
                          );
                        },
                  child: Text(_currentPage == 2 ? 'Get Started' : 'Next'),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildPage1() {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: DJISpacing.xxxl),
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          const AppLogo(size: 120)
              .animate()
              .fadeIn(duration: 600.ms)
              .scale(
                begin: const Offset(0.8, 0.8),
                end: const Offset(1.0, 1.0),
                duration: 600.ms,
              ),
          const SizedBox(height: DJISpacing.xxxl),
          const Text(
            'Give Your AI Eyes',
            textAlign: TextAlign.center,
            style: TextStyle(
              color: DJIColors.textPrimary,
              fontSize: 28,
              fontWeight: FontWeight.w600,
              letterSpacing: -0.5,
            ),
          )
              .animate()
              .fadeIn(delay: 200.ms, duration: 500.ms),
          const SizedBox(height: DJISpacing.lg),
          const Text(
            'Physical MCP connects your cameras\nto any AI assistant — Claude, ChatGPT,\nGemini, and more.',
            textAlign: TextAlign.center,
            style: TextStyle(
              color: DJIColors.textSecondary,
              fontSize: 16,
              height: 1.5,
            ),
          )
              .animate()
              .fadeIn(delay: 400.ms, duration: 500.ms),
        ],
      ),
    );
  }

  Widget _buildPage2() {
    final steps = widget.isEmbedded
        ? [
            (Icons.usb_rounded, 'Plug in your camera', 'USB or built-in webcam'),
            (Icons.smart_toy_rounded, 'Connect any AI', 'Claude, ChatGPT, Gemini, and more'),
            (Icons.notifications_active_rounded, 'Monitor your world', 'Set up rules and get alerts'),
          ]
        : [
            (Icons.download_rounded, 'Install the server', 'pip install physical-mcp'),
            (Icons.wifi_rounded, 'Connect this app', 'Auto-discovers on your network'),
            (Icons.auto_awesome_rounded, 'Your AI can see', 'Monitor, watch, and get alerts'),
          ];

    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: DJISpacing.xxxl),
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          for (int i = 0; i < steps.length; i++) ...[
            _buildStep(
              icon: steps[i].$1,
              number: '${i + 1}',
              title: steps[i].$2,
              subtitle: steps[i].$3,
            )
                .animate()
                .fadeIn(
                  delay: Duration(milliseconds: i * 150),
                  duration: 400.ms,
                )
                .slideX(begin: 0.05, end: 0),
            if (i < steps.length - 1) const SizedBox(height: DJISpacing.xxl),
          ],
        ],
      ),
    );
  }

  Widget _buildStep({
    required IconData icon,
    required String number,
    required String title,
    required String subtitle,
  }) {
    return Row(
      children: [
        Container(
          width: 52,
          height: 52,
          decoration: BoxDecoration(
            color: DJIColors.primary.withValues(alpha: 0.1),
            borderRadius: BorderRadius.circular(DJIRadius.md),
            border: Border.all(
              color: DJIColors.primary.withValues(alpha: 0.2),
            ),
          ),
          child: Icon(icon, color: DJIColors.primary, size: 24),
        ),
        const SizedBox(width: DJISpacing.lg),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                title,
                style: const TextStyle(
                  color: DJIColors.textPrimary,
                  fontSize: 17,
                  fontWeight: FontWeight.w600,
                ),
              ),
              const SizedBox(height: 2),
              Text(
                subtitle,
                style: TextStyle(
                  color: DJIColors.textSecondary,
                  fontSize: 14,
                  fontFamily: subtitle.startsWith('pip') || subtitle.startsWith('physical-')
                      ? 'SF Mono'
                      : null,
                  fontFamilyFallback: subtitle.startsWith('pip') || subtitle.startsWith('physical-')
                      ? const ['Menlo', 'monospace']
                      : null,
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }

  Widget _buildPage3() {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: DJISpacing.xxxl),
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Container(
            width: 80,
            height: 80,
            decoration: BoxDecoration(
              color: DJIColors.primary.withValues(alpha: 0.1),
              borderRadius: BorderRadius.circular(DJIRadius.xl),
              border: Border.all(
                color: DJIColors.primary.withValues(alpha: 0.3),
              ),
            ),
            child: const Icon(
              Icons.smart_toy_rounded,
              color: DJIColors.primary,
              size: 40,
            ),
          )
              .animate()
              .fadeIn(duration: 500.ms)
              .scale(
                begin: const Offset(0.8, 0.8),
                end: const Offset(1.0, 1.0),
                duration: 500.ms,
              ),
          const SizedBox(height: DJISpacing.xxxl),
          Text(
            widget.isEmbedded
                ? "Almost There!"
                : "You're All Set",
            textAlign: TextAlign.center,
            style: const TextStyle(
              color: DJIColors.textPrimary,
              fontSize: 28,
              fontWeight: FontWeight.w600,
              letterSpacing: -0.5,
            ),
          )
              .animate()
              .fadeIn(delay: 200.ms, duration: 500.ms),
          const SizedBox(height: DJISpacing.lg),
          Text(
            widget.isEmbedded
                ? "Plug in your camera, then connect\nan AI app like ChatGPT or Claude\nto start seeing your world."
                : "We'll search your network for a\ncamera server. Make sure it's running\nbefore continuing.",
            textAlign: TextAlign.center,
            style: const TextStyle(
              color: DJIColors.textSecondary,
              fontSize: 16,
              height: 1.5,
            ),
          )
              .animate()
              .fadeIn(delay: 400.ms, duration: 500.ms),
          if (widget.isEmbedded) ...[
            const SizedBox(height: DJISpacing.xxl),
            Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                _buildAppChip(Icons.smart_toy_outlined, 'Claude'),
                const SizedBox(width: DJISpacing.md),
                _buildAppChip(Icons.chat_bubble_outline_rounded, 'ChatGPT'),
                const SizedBox(width: DJISpacing.md),
                _buildAppChip(Icons.code_rounded, 'Cursor'),
              ],
            )
                .animate()
                .fadeIn(delay: 600.ms, duration: 400.ms),
            const SizedBox(height: DJISpacing.lg),
            Text(
              "We'll help you set this up next",
              textAlign: TextAlign.center,
              style: TextStyle(
                color: DJIColors.textTertiary,
                fontSize: 13,
              ),
            )
                .animate()
                .fadeIn(delay: 700.ms, duration: 400.ms),
          ],
        ],
      ),
    );
  }

  Widget _buildAppChip(IconData icon, String label) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
      decoration: BoxDecoration(
        color: DJIColors.surface,
        borderRadius: BorderRadius.circular(DJIRadius.round),
        border: Border.all(color: DJIColors.divider),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, color: DJIColors.textSecondary, size: 14),
          const SizedBox(width: 4),
          Text(
            label,
            style: const TextStyle(
              color: DJIColors.textSecondary,
              fontSize: 12,
              fontWeight: FontWeight.w500,
            ),
          ),
        ],
      ),
    );
  }
}
