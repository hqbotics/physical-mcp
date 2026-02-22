import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_animate/flutter_animate.dart';

import '../services/ai_app_service.dart';
import '../theme/dji_theme.dart';
import '../widgets/glassmorphic_card.dart';

/// Screen that guides users to connect an AI chat app to Physical MCP.
///
/// Shows installed/detected AI apps with one-tap configuration,
/// manual setup steps for HTTP-only apps (ChatGPT), and an API
/// endpoint copy card for developers.
class ConnectAIScreen extends StatefulWidget {
  final int serverPort;
  final String? tunnelUrl;
  final VoidCallback? onDone;

  const ConnectAIScreen({
    super.key,
    this.serverPort = 8090,
    this.tunnelUrl,
    this.onDone,
  });

  @override
  State<ConnectAIScreen> createState() => _ConnectAIScreenState();
}

class _ConnectAIScreenState extends State<ConnectAIScreen> {
  List<AIAppInfo> _apps = [];
  String _lanIp = '127.0.0.1';
  bool _loading = true;
  String? _expandedApp; // Name of app whose details are expanded

  @override
  void initState() {
    super.initState();
    _detect();
  }

  Future<void> _detect() async {
    final ip = await AIAppService.getLanIp(widget.serverPort);
    final apps = AIAppService.detectApps();
    if (mounted) {
      setState(() {
        _lanIp = ip;
        _apps = apps;
        _loading = false;
      });
    }
  }

  Future<void> _configureApp(AIAppInfo app) async {
    final success = await AIAppService.configureApp(app);
    if (mounted) {
      setState(() {}); // Refresh status
      if (success) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('${app.name} configured! ${app.setupHint}'),
            backgroundColor: DJIColors.secondary,
            duration: const Duration(seconds: 4),
          ),
        );
      } else {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('Failed to configure ${app.name}'),
            backgroundColor: DJIColors.danger,
          ),
        );
      }
    }
  }

  void _copyToClipboard(String text, String label) {
    Clipboard.setData(ClipboardData(text: text));
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text('$label copied!'),
        backgroundColor: DJIColors.primary,
        duration: const Duration(seconds: 2),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: DJIColors.background,
      body: SafeArea(
        child: _loading
            ? const Center(child: CircularProgressIndicator())
            : ListView(
                padding: const EdgeInsets.all(DJISpacing.xl),
                children: [
                  // Header
                  const Text(
                    'Connect an AI App',
                    style: TextStyle(
                      color: DJIColors.textPrimary,
                      fontSize: 28,
                      fontWeight: FontWeight.w600,
                      letterSpacing: -0.5,
                    ),
                  ),
                  const SizedBox(height: DJISpacing.sm),
                  const Text(
                    'Your camera is live! Choose an AI chat app\n'
                    'to give it eyes.',
                    style: TextStyle(
                      color: DJIColors.textSecondary,
                      fontSize: 15,
                      height: 1.4,
                    ),
                  ),
                  const SizedBox(height: DJISpacing.xxl),

                  // App cards
                  ..._apps.asMap().entries.map((entry) {
                    final index = entry.key;
                    final app = entry.value;
                    return Padding(
                      padding: const EdgeInsets.only(bottom: DJISpacing.md),
                      child: _buildAppCard(app)
                          .animate()
                          .fadeIn(
                            delay: Duration(milliseconds: 80 * index),
                            duration: 300.ms,
                          )
                          .slideY(
                            begin: 0.1,
                            end: 0,
                            delay: Duration(milliseconds: 80 * index),
                            duration: 300.ms,
                          ),
                    );
                  }),

                  const SizedBox(height: DJISpacing.lg),

                  // API Endpoint card (for developers)
                  _buildApiEndpointCard()
                      .animate()
                      .fadeIn(delay: 500.ms, duration: 300.ms),

                  const SizedBox(height: DJISpacing.xxl),

                  // Done / Skip button
                  if (widget.onDone != null)
                    Center(
                      child: TextButton(
                        onPressed: widget.onDone,
                        child: Text(
                          AIAppService.hasAnyConfigured(_apps)
                              ? 'Done'
                              : 'Skip for now',
                          style: const TextStyle(
                            color: DJIColors.textSecondary,
                            fontSize: 15,
                          ),
                        ),
                      ),
                    ),
                  const SizedBox(height: DJISpacing.xxl),
                ],
              ),
      ),
    );
  }

  Widget _buildAppCard(AIAppInfo app) {
    final isExpanded = _expandedApp == app.name;

    return GlassmorphicCard(
      onTap: () {
        setState(() {
          _expandedApp = isExpanded ? null : app.name;
        });
      },
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // Header row
          Row(
            children: [
              // Status indicator
              Container(
                width: 10,
                height: 10,
                decoration: BoxDecoration(
                  shape: BoxShape.circle,
                  color: _statusColor(app.status),
                ),
              ),
              const SizedBox(width: DJISpacing.md),
              // App name
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      app.name,
                      style: const TextStyle(
                        color: DJIColors.textPrimary,
                        fontSize: 16,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                    const SizedBox(height: 2),
                    Text(
                      _statusText(app.status),
                      style: TextStyle(
                        color: _statusColor(app.status),
                        fontSize: 12,
                      ),
                    ),
                  ],
                ),
              ),
              // Action button or chevron
              if (app.status == AIAppStatus.notConfigured)
                _ConfigureButton(onTap: () => _configureApp(app))
              else if (app.status == AIAppStatus.configured)
                const Icon(Icons.check_circle_rounded,
                    color: DJIColors.secondary, size: 24)
              else if (app.status == AIAppStatus.manualSetup)
                Icon(
                  isExpanded
                      ? Icons.keyboard_arrow_up_rounded
                      : Icons.keyboard_arrow_down_rounded,
                  color: DJIColors.textTertiary,
                )
              else
                const Icon(Icons.remove_circle_outline_rounded,
                    color: DJIColors.textDisabled, size: 20),
            ],
          ),

          // Expanded content
          if (isExpanded) ...[
            const SizedBox(height: DJISpacing.md),
            const Divider(color: DJIColors.divider),
            const SizedBox(height: DJISpacing.md),
            if (app.transport == 'http')
              _buildChatGPTSteps()
            else if (app.status == AIAppStatus.configured)
              _buildConfiguredInfo(app)
            else if (app.status == AIAppStatus.notInstalled)
              Text(
                '${app.name} doesn\'t appear to be installed on this Mac.\n'
                'Install it first, then come back here.',
                style: const TextStyle(
                  color: DJIColors.textTertiary,
                  fontSize: 13,
                  height: 1.5,
                ),
              ),
          ],
        ],
      ),
    );
  }

  Widget _buildChatGPTSteps() {
    final tunnelUrl = widget.tunnelUrl;
    final hasTunnel = tunnelUrl != null && tunnelUrl.isNotEmpty;
    final String mcpUrl = hasTunnel ? '$tunnelUrl/mcp' : '';

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        // Tunnel status indicator
        Container(
          width: double.infinity,
          padding: const EdgeInsets.all(DJISpacing.md),
          margin: const EdgeInsets.only(bottom: DJISpacing.md),
          decoration: BoxDecoration(
            color: hasTunnel
                ? DJIColors.secondary.withValues(alpha: 0.1)
                : DJIColors.warning.withValues(alpha: 0.1),
            borderRadius: BorderRadius.circular(DJIRadius.sm),
            border: Border.all(
              color: hasTunnel
                  ? DJIColors.secondary.withValues(alpha: 0.3)
                  : DJIColors.warning.withValues(alpha: 0.3),
            ),
          ),
          child: Row(
            children: [
              Icon(
                hasTunnel ? Icons.cloud_done_rounded : Icons.cloud_off_rounded,
                size: 16,
                color: hasTunnel ? DJIColors.secondary : DJIColors.warning,
              ),
              const SizedBox(width: DJISpacing.sm),
              Expanded(
                child: Text(
                  hasTunnel
                      ? 'Secure tunnel active'
                      : 'Setting up secure tunnel...',
                  style: TextStyle(
                    color: hasTunnel ? DJIColors.secondary : DJIColors.warning,
                    fontSize: 12,
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ),
              if (!hasTunnel)
                const SizedBox(
                  width: 14,
                  height: 14,
                  child: CircularProgressIndicator(
                    strokeWidth: 2,
                    color: DJIColors.warning,
                  ),
                ),
            ],
          ),
        ),

        // Requirements note
        Container(
          width: double.infinity,
          padding: const EdgeInsets.all(DJISpacing.sm),
          margin: const EdgeInsets.only(bottom: DJISpacing.md),
          decoration: BoxDecoration(
            color: DJIColors.textTertiary.withValues(alpha: 0.08),
            borderRadius: BorderRadius.circular(DJIRadius.sm),
          ),
          child: const Row(
            children: [
              Icon(Icons.info_outline_rounded,
                  size: 13, color: DJIColors.textTertiary),
              SizedBox(width: DJISpacing.sm),
              Expanded(
                child: Text(
                  'Requires ChatGPT Pro, Team, Enterprise, or Edu plan '
                  'with Developer Mode enabled.',
                  style: TextStyle(
                    color: DJIColors.textTertiary,
                    fontSize: 11,
                    height: 1.3,
                  ),
                ),
              ),
            ],
          ),
        ),

        // Steps
        const _StepRow(
          number: 1,
          text: 'Open chatgpt.com',
        ),
        const _StepRow(
          number: 2,
          text:
              'Settings \u2192 Apps & Connectors \u2192 Advanced \u2192 Enable Developer Mode',
        ),
        const _StepRow(
          number: 3,
          text: 'Go to Connectors \u2192 Create',
        ),
        const _StepRow(
          number: 4,
          text: 'Name: Physical MCP',
        ),
        const _StepRow(
          number: 5,
          text: 'Paste this exact URL in the URL field:',
        ),
        const SizedBox(height: DJISpacing.sm),
        if (hasTunnel)
          GestureDetector(
            onTap: () => _copyToClipboard(mcpUrl, 'MCP URL'),
            child: Container(
              width: double.infinity,
              padding: const EdgeInsets.all(DJISpacing.md),
              decoration: BoxDecoration(
                color: DJIColors.background,
                borderRadius: BorderRadius.circular(DJIRadius.sm),
                border: Border.all(
                    color: DJIColors.primary.withValues(alpha: 0.3)),
              ),
              child: Row(
                children: [
                  Expanded(
                    child: Text(
                      mcpUrl,
                      style: const TextStyle(
                        color: DJIColors.primary,
                        fontSize: 12,
                        fontFamily: 'monospace',
                      ),
                      overflow: TextOverflow.ellipsis,
                    ),
                  ),
                  const SizedBox(width: DJISpacing.sm),
                  const Icon(Icons.copy_rounded,
                      size: 16, color: DJIColors.primary),
                ],
              ),
            ),
          )
        else
          Container(
            width: double.infinity,
            padding: const EdgeInsets.all(DJISpacing.md),
            decoration: BoxDecoration(
              color: DJIColors.background,
              borderRadius: BorderRadius.circular(DJIRadius.sm),
              border: Border.all(color: DJIColors.divider),
            ),
            child: const Text(
              'Waiting for tunnel...',
              style: TextStyle(
                color: DJIColors.textDisabled,
                fontSize: 12,
                fontStyle: FontStyle.italic,
              ),
            ),
          ),
        const SizedBox(height: DJISpacing.md),
        const _StepRow(
          number: 6,
          text: 'Click Verify \u2192 Done!',
        ),
      ],
    );
  }

  Widget _buildConfiguredInfo(AIAppInfo app) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            const Icon(Icons.check_circle_rounded,
                color: DJIColors.secondary, size: 16),
            const SizedBox(width: DJISpacing.sm),
            const Expanded(
              child: Text(
                'Physical MCP is configured!',
                style: TextStyle(
                  color: DJIColors.secondary,
                  fontSize: 13,
                  fontWeight: FontWeight.w600,
                ),
              ),
            ),
          ],
        ),
        const SizedBox(height: DJISpacing.sm),
        Text(
          app.setupHint,
          style: const TextStyle(
            color: DJIColors.textTertiary,
            fontSize: 12,
            height: 1.4,
          ),
        ),
      ],
    );
  }

  Widget _buildApiEndpointCard() {
    final httpUrl = 'http://$_lanIp:${widget.serverPort}';
    return GlassmorphicCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Icon(Icons.code_rounded,
                  color: DJIColors.textTertiary, size: 18),
              const SizedBox(width: DJISpacing.md),
              const Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      'API Endpoint',
                      style: TextStyle(
                        color: DJIColors.textPrimary,
                        fontSize: 16,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                    SizedBox(height: 2),
                    Text(
                      'For developers & custom integrations',
                      style: TextStyle(
                        color: DJIColors.textTertiary,
                        fontSize: 12,
                      ),
                    ),
                  ],
                ),
              ),
            ],
          ),
          const SizedBox(height: DJISpacing.md),
          GestureDetector(
            onTap: () => _copyToClipboard(httpUrl, 'API URL'),
            child: Container(
              width: double.infinity,
              padding: const EdgeInsets.all(DJISpacing.md),
              decoration: BoxDecoration(
                color: DJIColors.background,
                borderRadius: BorderRadius.circular(DJIRadius.sm),
                border: Border.all(color: DJIColors.divider),
              ),
              child: Row(
                children: [
                  Expanded(
                    child: Text(
                      httpUrl,
                      style: const TextStyle(
                        color: DJIColors.textPrimary,
                        fontSize: 13,
                        fontFamily: 'monospace',
                      ),
                    ),
                  ),
                  const Icon(Icons.copy_rounded,
                      size: 16, color: DJIColors.textTertiary),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }

  Color _statusColor(AIAppStatus status) {
    switch (status) {
      case AIAppStatus.configured:
        return DJIColors.secondary;
      case AIAppStatus.notConfigured:
        return DJIColors.primary;
      case AIAppStatus.manualSetup:
        return DJIColors.warning;
      case AIAppStatus.notInstalled:
        return DJIColors.textDisabled;
    }
  }

  String _statusText(AIAppStatus status) {
    switch (status) {
      case AIAppStatus.configured:
        return 'Configured';
      case AIAppStatus.notConfigured:
        return 'Installed \u00b7 Not set up';
      case AIAppStatus.manualSetup:
        return 'Manual setup required';
      case AIAppStatus.notInstalled:
        return 'Not installed';
    }
  }
}

/// Small "Configure" button.
class _ConfigureButton extends StatelessWidget {
  final VoidCallback onTap;

  const _ConfigureButton({required this.onTap});

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onTap,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
        decoration: BoxDecoration(
          color: DJIColors.primary.withValues(alpha: 0.15),
          borderRadius: BorderRadius.circular(DJIRadius.round),
          border: Border.all(color: DJIColors.primary.withValues(alpha: 0.3)),
        ),
        child: const Text(
          'Configure',
          style: TextStyle(
            color: DJIColors.primary,
            fontSize: 12,
            fontWeight: FontWeight.w600,
          ),
        ),
      ),
    );
  }
}

/// A numbered step row for setup instructions.
class _StepRow extends StatelessWidget {
  final int number;
  final String text;

  const _StepRow({required this.number, required this.text});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 6),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            width: 20,
            height: 20,
            alignment: Alignment.center,
            decoration: BoxDecoration(
              shape: BoxShape.circle,
              color: DJIColors.textTertiary.withValues(alpha: 0.2),
            ),
            child: Text(
              '$number',
              style: const TextStyle(
                color: DJIColors.textSecondary,
                fontSize: 11,
                fontWeight: FontWeight.w600,
              ),
            ),
          ),
          const SizedBox(width: DJISpacing.sm),
          Expanded(
            child: Text(
              text,
              style: const TextStyle(
                color: DJIColors.textSecondary,
                fontSize: 13,
                height: 1.4,
              ),
            ),
          ),
        ],
      ),
    );
  }
}
