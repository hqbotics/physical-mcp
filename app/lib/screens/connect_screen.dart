import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_animate/flutter_animate.dart';
import 'package:url_launcher/url_launcher.dart';

import '../models/server_config.dart';
import '../theme/dji_theme.dart';
import '../widgets/glassmorphic_card.dart';
import '../widgets/status_dot.dart';

/// Connect screen — find and connect to a physical-mcp backend.
///
/// In consumer (embedded) mode: shows camera troubleshooting tips.
/// In developer mode: shows pip install instructions and manual IP entry.
class ConnectScreen extends StatefulWidget {
  final List<ServerConfig> discoveredServers;
  final bool isScanning;
  final bool isEmbedded;
  final void Function(ServerConfig config) onConnect;
  final VoidCallback onRescan;
  final VoidCallback? onRestartServer;

  const ConnectScreen({
    super.key,
    this.discoveredServers = const [],
    this.isScanning = false,
    this.isEmbedded = false,
    required this.onConnect,
    required this.onRescan,
    this.onRestartServer,
  });

  @override
  State<ConnectScreen> createState() => _ConnectScreenState();
}

class _ConnectScreenState extends State<ConnectScreen> {
  final _hostController = TextEditingController(text: '');
  final _portController = TextEditingController(text: '8090');
  final _tokenController = TextEditingController();
  bool _showManual = false;

  @override
  void dispose() {
    _hostController.dispose();
    _portController.dispose();
    _tokenController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: DJIColors.background,
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(DJISpacing.xl),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const SizedBox(height: DJISpacing.xxl),

              // Header
              Text(
                widget.isEmbedded
                    ? 'Looking for\nyour camera'
                    : 'Connect to\nyour camera',
                style: const TextStyle(
                  color: DJIColors.textPrimary,
                  fontSize: 32,
                  fontWeight: FontWeight.w600,
                  letterSpacing: -0.5,
                  height: 1.15,
                ),
              )
                  .animate()
                  .fadeIn(duration: 400.ms)
                  .slideY(begin: 0.1, end: 0, duration: 400.ms),

              const SizedBox(height: DJISpacing.sm),

              Text(
                widget.isScanning
                    ? 'Scanning your network...'
                    : widget.discoveredServers.isEmpty
                        ? widget.isEmbedded
                            ? 'No cameras detected'
                            : 'No servers found on your network'
                        : '${widget.discoveredServers.length} server${widget.discoveredServers.length > 1 ? 's' : ''} found',
                style: const TextStyle(
                  color: DJIColors.textSecondary,
                  fontSize: 15,
                ),
              ),

              const SizedBox(height: DJISpacing.xxxl),

              // Discovered servers
              if (widget.discoveredServers.isNotEmpty)
                ...widget.discoveredServers.asMap().entries.map((entry) {
                  final idx = entry.key;
                  final server = entry.value;
                  return Padding(
                    padding: const EdgeInsets.only(bottom: DJISpacing.md),
                    child: _ServerCard(
                      server: server,
                      onTap: () => widget.onConnect(server),
                    )
                        .animate()
                        .fadeIn(
                          delay: Duration(milliseconds: 200 + idx * 100),
                          duration: 400.ms,
                        )
                        .slideX(
                          begin: 0.05,
                          end: 0,
                          delay: Duration(milliseconds: 200 + idx * 100),
                          duration: 400.ms,
                        ),
                  );
                }),

              // Scanning indicator
              if (widget.isScanning)
                Padding(
                  padding: const EdgeInsets.symmetric(vertical: DJISpacing.lg),
                  child: Center(
                    child: SizedBox(
                      width: 24,
                      height: 24,
                      child: CircularProgressIndicator(
                        color: DJIColors.primary,
                        strokeWidth: 2,
                      ),
                    ),
                  ),
                ),

              // Help card when no servers found
              if (widget.discoveredServers.isEmpty && !widget.isScanning)
                widget.isEmbedded
                    ? _buildConsumerHelp()
                    : _buildDeveloperHelp(),

              const Spacer(),

              // Manual entry / advanced toggle
              if (!_showManual)
                Center(
                  child: TextButton.icon(
                    onPressed: () => setState(() => _showManual = true),
                    icon: const Icon(Icons.edit_rounded, size: 16),
                    label: Text(widget.isEmbedded
                        ? 'Connect to remote server'
                        : 'Enter IP manually'),
                  ),
                )
              else
                _buildManualEntry(),

              const SizedBox(height: DJISpacing.lg),

              // Action buttons row
              Row(
                children: [
                  // Restart server (embedded only)
                  if (widget.isEmbedded && widget.onRestartServer != null) ...[
                    Expanded(
                      child: OutlinedButton.icon(
                        onPressed: widget.onRestartServer,
                        icon: const Icon(Icons.restart_alt_rounded, size: 18),
                        label: const Text('Restart Server'),
                      ),
                    ),
                    const SizedBox(width: DJISpacing.md),
                  ],
                  // Rescan button
                  Expanded(
                    child: OutlinedButton.icon(
                      onPressed: widget.isScanning ? null : widget.onRescan,
                      icon: const Icon(Icons.refresh_rounded, size: 18),
                      label:
                          Text(widget.isScanning ? 'Scanning...' : 'Scan again'),
                    ),
                  ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }

  /// Consumer help — camera troubleshooting (no pip install).
  Widget _buildConsumerHelp() {
    return GlassmorphicCard(
      padding: const EdgeInsets.all(DJISpacing.lg),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Row(
            children: [
              Icon(Icons.videocam_off_rounded,
                  color: DJIColors.warning, size: 18),
              SizedBox(width: DJISpacing.sm),
              Text(
                'Camera Not Found',
                style: TextStyle(
                  color: DJIColors.textPrimary,
                  fontSize: 14,
                  fontWeight: FontWeight.w600,
                ),
              ),
            ],
          ),
          const SizedBox(height: DJISpacing.md),
          _troubleshootItem(
            Icons.usb_rounded,
            'Make sure your USB camera is plugged in',
          ),
          const SizedBox(height: DJISpacing.sm),
          _troubleshootItem(
            Icons.security_rounded,
            'Check System Settings \u2192 Privacy \u2192 Camera',
          ),
          const SizedBox(height: DJISpacing.sm),
          _troubleshootItem(
            Icons.refresh_rounded,
            'Try unplugging and reconnecting the camera',
          ),
          const SizedBox(height: DJISpacing.md),
          Center(
            child: TextButton.icon(
              onPressed: () => launchUrl(
                Uri.parse('https://github.com/idnaaa/physical-mcp/wiki/Troubleshooting'),
                mode: LaunchMode.externalApplication,
              ),
              icon: const Icon(Icons.help_outline_rounded, size: 14),
              label: const Text('Need help?'),
              style: TextButton.styleFrom(
                textStyle: const TextStyle(fontSize: 12),
              ),
            ),
          ),
        ],
      ),
    )
        .animate()
        .fadeIn(delay: 300.ms, duration: 400.ms);
  }

  Widget _troubleshootItem(IconData icon, String text) {
    return Row(
      children: [
        Icon(icon, color: DJIColors.textTertiary, size: 16),
        const SizedBox(width: DJISpacing.sm),
        Expanded(
          child: Text(
            text,
            style: const TextStyle(
              color: DJIColors.textSecondary,
              fontSize: 13,
            ),
          ),
        ),
      ],
    );
  }

  /// Developer help — pip install instructions.
  Widget _buildDeveloperHelp() {
    return GlassmorphicCard(
      padding: const EdgeInsets.all(DJISpacing.lg),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Row(
            children: [
              Icon(Icons.lightbulb_outline_rounded,
                  color: DJIColors.warning, size: 18),
              SizedBox(width: DJISpacing.sm),
              Text(
                'Quick Start',
                style: TextStyle(
                  color: DJIColors.textPrimary,
                  fontSize: 14,
                  fontWeight: FontWeight.w600,
                ),
              ),
            ],
          ),
          const SizedBox(height: DJISpacing.md),
          _helpStep('1.', 'Install:', 'pip install physical-mcp'),
          const SizedBox(height: DJISpacing.sm),
          _helpStep('2.', 'Run:', 'physical-mcp'),
          const SizedBox(height: DJISpacing.sm),
          const Text(
            '3.  This app will find it automatically',
            style: TextStyle(
              color: DJIColors.textSecondary,
              fontSize: 13,
            ),
          ),
          const SizedBox(height: DJISpacing.md),
          Row(
            children: [
              Expanded(
                child: OutlinedButton.icon(
                  onPressed: () {
                    Clipboard.setData(const ClipboardData(
                        text: 'pip install physical-mcp && physical-mcp'));
                    ScaffoldMessenger.of(context).showSnackBar(
                      const SnackBar(
                        content: Text('Command copied!'),
                        duration: Duration(seconds: 2),
                      ),
                    );
                  },
                  icon: const Icon(Icons.copy_rounded, size: 14),
                  label: const Text('Copy command'),
                  style: OutlinedButton.styleFrom(
                    padding: const EdgeInsets.symmetric(vertical: 8),
                    textStyle: const TextStyle(fontSize: 12),
                  ),
                ),
              ),
              const SizedBox(width: DJISpacing.md),
              Expanded(
                child: TextButton.icon(
                  onPressed: () => launchUrl(
                    Uri.parse('https://github.com/idnaaa/physical-mcp'),
                    mode: LaunchMode.externalApplication,
                  ),
                  icon: const Icon(Icons.open_in_new_rounded, size: 14),
                  label: const Text('View docs'),
                  style: TextButton.styleFrom(
                    padding: const EdgeInsets.symmetric(vertical: 8),
                    textStyle: const TextStyle(fontSize: 12),
                  ),
                ),
              ),
            ],
          ),
        ],
      ),
    )
        .animate()
        .fadeIn(delay: 300.ms, duration: 400.ms);
  }

  Widget _helpStep(String num, String label, String code) {
    return Row(
      children: [
        Text(
          '$num  $label ',
          style: const TextStyle(
            color: DJIColors.textSecondary,
            fontSize: 13,
          ),
        ),
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
          decoration: BoxDecoration(
            color: DJIColors.surfaceElevated,
            borderRadius: BorderRadius.circular(4),
          ),
          child: Text(
            code,
            style: const TextStyle(
              fontFamily: 'SF Mono',
              fontFamilyFallback: ['Menlo', 'monospace'],
              color: DJIColors.primary,
              fontSize: 12,
            ),
          ),
        ),
      ],
    );
  }

  Widget _buildManualEntry() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          widget.isEmbedded ? 'Remote Server' : 'Manual Connection',
          style: const TextStyle(
            color: DJIColors.textSecondary,
            fontSize: 13,
            fontWeight: FontWeight.w600,
          ),
        ),
        const SizedBox(height: DJISpacing.md),

        // Host + Port row
        Row(
          children: [
            Expanded(
              flex: 3,
              child: TextField(
                controller: _hostController,
                style: const TextStyle(color: DJIColors.textPrimary),
                decoration: const InputDecoration(
                  labelText: 'IP Address',
                  hintText: '192.168.1.100',
                ),
              ),
            ),
            const SizedBox(width: DJISpacing.md),
            Expanded(
              child: TextField(
                controller: _portController,
                style: const TextStyle(color: DJIColors.textPrimary),
                keyboardType: TextInputType.number,
                decoration: const InputDecoration(
                  labelText: 'Port',
                ),
              ),
            ),
          ],
        ),
        const SizedBox(height: DJISpacing.md),

        // Auth token (optional)
        TextField(
          controller: _tokenController,
          style: const TextStyle(color: DJIColors.textPrimary),
          obscureText: true,
          decoration: const InputDecoration(
            labelText: 'Auth token (optional)',
            hintText: 'Leave empty if not set',
          ),
        ),
        const SizedBox(height: DJISpacing.lg),

        // Connect button
        SizedBox(
          width: double.infinity,
          child: ElevatedButton(
            onPressed: _hostController.text.isNotEmpty
                ? () {
                    final port =
                        int.tryParse(_portController.text) ?? 8090;
                    widget.onConnect(ServerConfig(
                      name: 'Physical MCP',
                      host: _hostController.text.trim(),
                      port: port,
                      authToken: _tokenController.text.isNotEmpty
                          ? _tokenController.text.trim()
                          : null,
                    ));
                  }
                : null,
            child: const Text('Connect'),
          ),
        ),
      ],
    )
        .animate()
        .fadeIn(duration: 300.ms)
        .slideY(begin: 0.05, end: 0, duration: 300.ms);
  }
}

class _ServerCard extends StatelessWidget {
  final ServerConfig server;
  final VoidCallback onTap;

  const _ServerCard({required this.server, required this.onTap});

  @override
  Widget build(BuildContext context) {
    return GlassmorphicCard(
      onTap: onTap,
      padding: const EdgeInsets.all(DJISpacing.lg),
      child: Row(
        children: [
          // Icon
          Container(
            width: 44,
            height: 44,
            decoration: BoxDecoration(
              color: DJIColors.primary.withValues(alpha: 0.1),
              borderRadius: BorderRadius.circular(DJIRadius.sm),
            ),
            child: const Icon(
              Icons.videocam_rounded,
              color: DJIColors.primary,
              size: 22,
            ),
          ),

          const SizedBox(width: DJISpacing.lg),

          // Server info
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  server.name,
                  style: const TextStyle(
                    color: DJIColors.textPrimary,
                    fontSize: 16,
                    fontWeight: FontWeight.w600,
                  ),
                ),
                const SizedBox(height: 2),
                Text(
                  '${server.host}:${server.port}',
                  style: const TextStyle(
                    color: DJIColors.textTertiary,
                    fontSize: 13,
                  ),
                ),
              ],
            ),
          ),

          // Status dot + arrow
          const StatusDot(isConnected: true, size: 8),
          const SizedBox(width: DJISpacing.md),
          const Icon(
            Icons.arrow_forward_ios_rounded,
            color: DJIColors.textTertiary,
            size: 14,
          ),
        ],
      ),
    );
  }
}
