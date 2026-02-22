import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../services/ai_app_service.dart';
import '../services/tunnel_manager.dart';
import '../theme/dji_theme.dart';
import '../widgets/glassmorphic_card.dart';

/// Settings screen — camera config, AI provider, notifications, about.
class SettingsScreen extends StatelessWidget {
  final String serverName;
  final String serverHost;
  final int serverPort;
  final bool isConnected;
  final String? aiProvider;
  final String? aiModel;
  final String? tunnelUrl;
  final TunnelState? tunnelState;
  final VoidCallback? onDisconnect;
  final VoidCallback? onConfigureProvider;
  final VoidCallback? onTestConnection;
  final VoidCallback? onManageAIApps;

  const SettingsScreen({
    super.key,
    required this.serverName,
    required this.serverHost,
    required this.serverPort,
    required this.isConnected,
    this.aiProvider,
    this.aiModel,
    this.tunnelUrl,
    this.tunnelState,
    this.onDisconnect,
    this.onConfigureProvider,
    this.onTestConnection,
    this.onManageAIApps,
  });

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: DJIColors.background,
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.all(DJISpacing.xl),
          children: [
            // Header
            const Text(
              'Settings',
              style: TextStyle(
                color: DJIColors.textPrimary,
                fontSize: 28,
                fontWeight: FontWeight.w600,
                letterSpacing: -0.5,
              ),
            ),
            const SizedBox(height: DJISpacing.xxxl),

            // ── Connection ─────────────────────────────────
            _SectionHeader(title: 'Connection'),
            const SizedBox(height: DJISpacing.md),
            GlassmorphicCard(
              child: Column(
                children: [
                  _SettingsRow(
                    icon: Icons.dns_rounded,
                    label: 'Server',
                    value: serverName,
                  ),
                  const Divider(color: DJIColors.divider),
                  _SettingsRow(
                    icon: Icons.language_rounded,
                    label: 'Address',
                    value: '$serverHost:$serverPort',
                  ),
                  const Divider(color: DJIColors.divider),
                  _SettingsRow(
                    icon: Icons.circle,
                    iconColor:
                        isConnected ? DJIColors.secondary : DJIColors.danger,
                    iconSize: 10,
                    label: 'Status',
                    value: isConnected ? 'Connected' : 'Disconnected',
                    valueColor:
                        isConnected ? DJIColors.secondary : DJIColors.danger,
                  ),
                ],
              ),
            ),
            const SizedBox(height: DJISpacing.md),
            Row(
              children: [
                Expanded(
                  child: OutlinedButton(
                    onPressed: onTestConnection,
                    child: const Text('Test Connection'),
                  ),
                ),
                const SizedBox(width: DJISpacing.md),
                Expanded(
                  child: OutlinedButton(
                    onPressed: onDisconnect,
                    style: OutlinedButton.styleFrom(
                      foregroundColor: DJIColors.danger,
                      side: BorderSide(
                        color: DJIColors.danger.withValues(alpha: 0.5),
                      ),
                    ),
                    child: const Text('Disconnect'),
                  ),
                ),
              ],
            ),

            const SizedBox(height: DJISpacing.xxxl),

            // ── HTTPS Tunnel ─────────────────────────────
            _SectionHeader(title: 'HTTPS Tunnel'),
            const SizedBox(height: DJISpacing.md),
            _TunnelCard(
              tunnelUrl: tunnelUrl,
              tunnelState: tunnelState ?? TunnelState.stopped,
            ),

            const SizedBox(height: DJISpacing.xxxl),

            // ── Connect AI Apps ──────────────────────────
            _SectionHeader(title: 'Connect AI Apps'),
            const SizedBox(height: DJISpacing.md),
            _AIAppsPreview(onManage: onManageAIApps),

            const SizedBox(height: DJISpacing.xxxl),

            // ── AI Provider ────────────────────────────────
            _SectionHeader(title: 'AI Provider'),
            const SizedBox(height: DJISpacing.md),
            GlassmorphicCard(
              onTap: onConfigureProvider,
              child: Column(
                children: [
                  _SettingsRow(
                    icon: Icons.auto_awesome_rounded,
                    label: 'Provider',
                    value: aiProvider ?? 'Not configured',
                  ),
                  if (aiModel != null) ...[
                    const Divider(color: DJIColors.divider),
                    _SettingsRow(
                      icon: Icons.memory_rounded,
                      label: 'Model',
                      value: aiModel!,
                    ),
                  ],
                ],
              ),
            ),

            const SizedBox(height: DJISpacing.xxxl),

            // ── About ──────────────────────────────────────
            _SectionHeader(title: 'About'),
            const SizedBox(height: DJISpacing.md),
            GlassmorphicCard(
              child: Column(
                children: [
                  _SettingsRow(
                    icon: Icons.info_outline_rounded,
                    label: 'Version',
                    value: '1.0.0',
                  ),
                  const Divider(color: DJIColors.divider),
                  _SettingsRow(
                    icon: Icons.code_rounded,
                    label: 'GitHub',
                    value: 'idnaaa/physical-mcp',
                  ),
                  const Divider(color: DJIColors.divider),
                  _SettingsRow(
                    icon: Icons.description_rounded,
                    label: 'License',
                    value: 'MIT',
                  ),
                ],
              ),
            ),

            const SizedBox(height: DJISpacing.xxxl),

            // Footer
            Center(
              child: Column(
                children: [
                  Text(
                    'Physical MCP',
                    style: TextStyle(
                      color: DJIColors.textTertiary,
                      fontSize: 13,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                  const SizedBox(height: 2),
                  Text(
                    'AI Vision for Your World',
                    style: TextStyle(
                      color: DJIColors.textDisabled,
                      fontSize: 11,
                    ),
                  ),
                  const SizedBox(height: 4),
                  Text(
                    'by HQBotics',
                    style: TextStyle(
                      color: DJIColors.textDisabled,
                      fontSize: 11,
                    ),
                  ),
                ],
              ),
            ),
            const SizedBox(height: DJISpacing.xxl),
          ],
        ),
      ),
    );
  }
}

class _SectionHeader extends StatelessWidget {
  final String title;

  const _SectionHeader({required this.title});

  @override
  Widget build(BuildContext context) {
    return Text(
      title.toUpperCase(),
      style: const TextStyle(
        color: DJIColors.textTertiary,
        fontSize: 11,
        fontWeight: FontWeight.w600,
        letterSpacing: 1.2,
      ),
    );
  }
}

class _SettingsRow extends StatelessWidget {
  final IconData icon;
  final Color? iconColor;
  final double? iconSize;
  final String label;
  final String value;
  final Color? valueColor;

  const _SettingsRow({
    required this.icon,
    this.iconColor,
    this.iconSize,
    required this.label,
    required this.value,
    this.valueColor,
  });

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: DJISpacing.md),
      child: Row(
        children: [
          Icon(
            icon,
            color: iconColor ?? DJIColors.textTertiary,
            size: iconSize ?? 18,
          ),
          const SizedBox(width: DJISpacing.md),
          Text(
            label,
            style: const TextStyle(
              color: DJIColors.textSecondary,
              fontSize: 14,
            ),
          ),
          const Spacer(),
          Text(
            value,
            style: TextStyle(
              color: valueColor ?? DJIColors.textPrimary,
              fontSize: 14,
              fontWeight: FontWeight.w500,
            ),
          ),
        ],
      ),
    );
  }
}

/// Shows the Cloudflare Tunnel status for remote/ChatGPT access.
class _TunnelCard extends StatelessWidget {
  final String? tunnelUrl;
  final TunnelState tunnelState;

  const _TunnelCard({this.tunnelUrl, required this.tunnelState});

  @override
  Widget build(BuildContext context) {
    final isRunning = tunnelState == TunnelState.running && tunnelUrl != null;
    final isStarting = tunnelState == TunnelState.starting;
    final isError = tunnelState == TunnelState.error;

    return GlassmorphicCard(
      child: Column(
        children: [
          _SettingsRow(
            icon: isRunning
                ? Icons.cloud_done_rounded
                : isStarting
                    ? Icons.cloud_upload_rounded
                    : Icons.cloud_off_rounded,
            iconColor: isRunning
                ? DJIColors.secondary
                : isStarting
                    ? DJIColors.warning
                    : DJIColors.textDisabled,
            label: 'Status',
            value: isRunning
                ? 'Active'
                : isStarting
                    ? 'Starting...'
                    : isError
                        ? 'Error'
                        : 'Stopped',
            valueColor: isRunning
                ? DJIColors.secondary
                : isStarting
                    ? DJIColors.warning
                    : DJIColors.textDisabled,
          ),
          if (isRunning && tunnelUrl != null) ...[
            const Divider(color: DJIColors.divider),
            Padding(
              padding: const EdgeInsets.symmetric(vertical: DJISpacing.md),
              child: GestureDetector(
                onTap: () {
                  Clipboard.setData(ClipboardData(text: tunnelUrl!));
                  ScaffoldMessenger.of(context).showSnackBar(
                    const SnackBar(
                      content: Text('Tunnel URL copied!'),
                      backgroundColor: DJIColors.primary,
                      duration: Duration(seconds: 2),
                    ),
                  );
                },
                child: Row(
                  children: [
                    const Icon(Icons.link_rounded,
                        color: DJIColors.textTertiary, size: 18),
                    const SizedBox(width: DJISpacing.md),
                    Expanded(
                      child: Text(
                        tunnelUrl!,
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
                        size: 14, color: DJIColors.primary),
                  ],
                ),
              ),
            ),
          ],
          if (!isRunning && !isStarting) ...[
            const Divider(color: DJIColors.divider),
            Padding(
              padding: const EdgeInsets.symmetric(vertical: DJISpacing.sm),
              child: Text(
                'Cloudflare Tunnel provides a public HTTPS URL\n'
                'required for ChatGPT and remote access.',
                style: TextStyle(
                  color: DJIColors.textTertiary,
                  fontSize: 11,
                  height: 1.4,
                ),
              ),
            ),
          ],
        ],
      ),
    );
  }
}

/// Quick preview of AI app connection status for the Settings screen.
class _AIAppsPreview extends StatelessWidget {
  final VoidCallback? onManage;

  const _AIAppsPreview({this.onManage});

  @override
  Widget build(BuildContext context) {
    final apps = AIAppService.detectApps();
    final configured = apps.where((a) => a.status == AIAppStatus.configured).length;
    final installed = apps.where((a) =>
        a.status == AIAppStatus.configured || a.status == AIAppStatus.notConfigured).length;

    return GlassmorphicCard(
      onTap: onManage,
      child: Column(
        children: [
          // Summary row
          Row(
            children: [
              const Icon(Icons.smart_toy_rounded,
                  color: DJIColors.primary, size: 20),
              const SizedBox(width: DJISpacing.md),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      '$configured of $installed apps connected',
                      style: const TextStyle(
                        color: DJIColors.textPrimary,
                        fontSize: 14,
                        fontWeight: FontWeight.w500,
                      ),
                    ),
                    const SizedBox(height: 2),
                    Text(
                      configured == 0
                          ? 'Tap to set up an AI app'
                          : 'Tap to manage connections',
                      style: const TextStyle(
                        color: DJIColors.textTertiary,
                        fontSize: 12,
                      ),
                    ),
                  ],
                ),
              ),
              const Icon(Icons.chevron_right_rounded,
                  color: DJIColors.textTertiary, size: 20),
            ],
          ),
          const SizedBox(height: DJISpacing.md),
          // App status dots
          Wrap(
            spacing: DJISpacing.md,
            runSpacing: DJISpacing.sm,
            children: apps
                .where((a) => a.status != AIAppStatus.notInstalled)
                .map((a) => Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Container(
                          width: 6,
                          height: 6,
                          decoration: BoxDecoration(
                            shape: BoxShape.circle,
                            color: a.status == AIAppStatus.configured
                                ? DJIColors.secondary
                                : DJIColors.textDisabled,
                          ),
                        ),
                        const SizedBox(width: 4),
                        Text(
                          a.name,
                          style: TextStyle(
                            color: a.status == AIAppStatus.configured
                                ? DJIColors.textSecondary
                                : DJIColors.textTertiary,
                            fontSize: 12,
                          ),
                        ),
                      ],
                    ))
                .toList(),
          ),
        ],
      ),
    );
  }
}
