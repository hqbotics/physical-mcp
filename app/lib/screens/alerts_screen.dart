import 'package:flutter/material.dart';
import 'package:flutter_animate/flutter_animate.dart';

import '../models/rule.dart';
import '../theme/dji_theme.dart';
import '../widgets/alert_card.dart';

/// Alerts timeline screen — vertical list of triggered events.
///
/// Newest first. Color-coded by priority. Pull to refresh.
class AlertsScreen extends StatelessWidget {
  final List<AlertEvent> alerts;
  final bool isLoading;
  final Future<void> Function()? onRefresh;
  final String? filterPriority;
  final void Function(String? priority)? onFilterChanged;

  const AlertsScreen({
    super.key,
    required this.alerts,
    this.isLoading = false,
    this.onRefresh,
    this.filterPriority,
    this.onFilterChanged,
  });

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: DJIColors.background,
      body: SafeArea(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // Header
            Padding(
              padding: const EdgeInsets.all(DJISpacing.xl),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text(
                    'Alerts',
                    style: TextStyle(
                      color: DJIColors.textPrimary,
                      fontSize: 28,
                      fontWeight: FontWeight.w600,
                      letterSpacing: -0.5,
                    ),
                  ),
                  const SizedBox(height: DJISpacing.sm),
                  Text(
                    '${alerts.length} event${alerts.length != 1 ? 's' : ''}',
                    style: const TextStyle(
                      color: DJIColors.textSecondary,
                      fontSize: 14,
                    ),
                  ),
                ],
              ),
            ),

            // Priority filter chips
            if (onFilterChanged != null)
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: DJISpacing.xl),
                child: SingleChildScrollView(
                  scrollDirection: Axis.horizontal,
                  child: Row(
                    children: [
                      _FilterChip(
                        label: 'All',
                        selected: filterPriority == null,
                        onTap: () => onFilterChanged!(null),
                      ),
                      const SizedBox(width: DJISpacing.sm),
                      ...['critical', 'high', 'medium', 'low'].map((p) {
                        return Padding(
                          padding:
                              const EdgeInsets.only(right: DJISpacing.sm),
                          child: _FilterChip(
                            label: p[0].toUpperCase() + p.substring(1),
                            selected: filterPriority == p,
                            color: DJIColors.forPriority(p),
                            onTap: () => onFilterChanged!(p),
                          ),
                        );
                      }),
                    ],
                  ),
                ),
              ),

            const SizedBox(height: DJISpacing.lg),

            // Alert list
            Expanded(
              child: alerts.isEmpty
                  ? _buildEmptyState()
                  : RefreshIndicator(
                      onRefresh: onRefresh ?? () async {},
                      color: DJIColors.primary,
                      backgroundColor: DJIColors.surface,
                      child: ListView.builder(
                        padding: const EdgeInsets.symmetric(
                          horizontal: DJISpacing.xl,
                        ),
                        itemCount: alerts.length,
                        itemBuilder: (context, index) {
                          return AlertCard(alert: alerts[index])
                              .animate()
                              .fadeIn(
                                delay: Duration(
                                    milliseconds: 50 * index.clamp(0, 10)),
                                duration: 300.ms,
                              );
                        },
                      ),
                    ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildEmptyState() {
    return Center(
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Icon(
            Icons.notifications_none_rounded,
            size: 64,
            color: DJIColors.textTertiary,
          ),
          const SizedBox(height: DJISpacing.lg),
          const Text(
            'No alerts yet',
            style: TextStyle(
              color: DJIColors.textSecondary,
              fontSize: 18,
              fontWeight: FontWeight.w600,
            ),
          ),
          const SizedBox(height: DJISpacing.sm),
          const Text(
            'Create watch rules and the AI will\nalert you when conditions are met',
            textAlign: TextAlign.center,
            style: TextStyle(
              color: DJIColors.textTertiary,
              fontSize: 14,
            ),
          ),
        ],
      ),
    );
  }
}

class _FilterChip extends StatelessWidget {
  final String label;
  final bool selected;
  final Color? color;
  final VoidCallback onTap;

  const _FilterChip({
    required this.label,
    required this.selected,
    this.color,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    final chipColor = color ?? DJIColors.primary;

    return GestureDetector(
      onTap: onTap,
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 150),
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 6),
        decoration: BoxDecoration(
          color:
              selected ? chipColor.withValues(alpha: 0.15) : Colors.transparent,
          borderRadius: BorderRadius.circular(DJIRadius.round),
          border: Border.all(
            color: selected
                ? chipColor.withValues(alpha: 0.5)
                : DJIColors.border,
          ),
        ),
        child: Text(
          label,
          style: TextStyle(
            color: selected ? chipColor : DJIColors.textSecondary,
            fontSize: 12,
            fontWeight: selected ? FontWeight.w600 : FontWeight.w400,
          ),
        ),
      ),
    );
  }
}
