import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../models/rule.dart';
import '../theme/dji_theme.dart';
import 'glassmorphic_card.dart';

/// Alert event card for the timeline view.
///
/// Shows timestamp, rule name, AI reasoning, priority indicator.
class AlertCard extends StatelessWidget {
  final AlertEvent alert;
  final VoidCallback? onTap;

  const AlertCard({
    super.key,
    required this.alert,
    this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    final priorityColor = DJIColors.forPriority(alert.priority);
    final timeStr = _formatTime(alert.timestamp);

    return GlassmorphicCard(
      onTap: onTap,
      padding: const EdgeInsets.all(DJISpacing.lg),
      margin: const EdgeInsets.only(bottom: DJISpacing.md),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // Priority indicator line
          Container(
            width: 3,
            height: 60,
            decoration: BoxDecoration(
              color: priorityColor,
              borderRadius: BorderRadius.circular(2),
            ),
          ),
          const SizedBox(width: DJISpacing.md),

          // Content
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                // Header: rule name + time
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    Expanded(
                      child: Text(
                        alert.ruleName,
                        style: const TextStyle(
                          color: DJIColors.textPrimary,
                          fontSize: 15,
                          fontWeight: FontWeight.w600,
                        ),
                        overflow: TextOverflow.ellipsis,
                      ),
                    ),
                    Text(
                      timeStr,
                      style: const TextStyle(
                        color: DJIColors.textTertiary,
                        fontSize: 11,
                      ),
                    ),
                  ],
                ),

                const SizedBox(height: DJISpacing.xs),

                // AI reasoning
                Text(
                  alert.reasoning,
                  style: const TextStyle(
                    color: DJIColors.textSecondary,
                    fontSize: 13,
                    height: 1.4,
                  ),
                  maxLines: 3,
                  overflow: TextOverflow.ellipsis,
                ),

                const SizedBox(height: DJISpacing.sm),

                // Priority + confidence badges
                Row(
                  children: [
                    _PriorityBadge(
                      priority: alert.priority,
                      color: priorityColor,
                    ),
                    const SizedBox(width: DJISpacing.sm),
                    Text(
                      '${(alert.confidence * 100).toInt()}% confidence',
                      style: const TextStyle(
                        color: DJIColors.textTertiary,
                        fontSize: 11,
                      ),
                    ),
                    if (alert.cameraId != null) ...[
                      const SizedBox(width: DJISpacing.sm),
                      Icon(
                        Icons.videocam_rounded,
                        size: 12,
                        color: DJIColors.textTertiary,
                      ),
                      const SizedBox(width: 2),
                      Text(
                        alert.cameraId!,
                        style: const TextStyle(
                          color: DJIColors.textTertiary,
                          fontSize: 11,
                        ),
                      ),
                    ],
                  ],
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  String _formatTime(DateTime time) {
    final now = DateTime.now();
    final diff = now.difference(time);

    if (diff.inMinutes < 1) return 'Just now';
    if (diff.inMinutes < 60) return '${diff.inMinutes}m ago';
    if (diff.inHours < 24) return '${diff.inHours}h ago';
    return DateFormat('MMM d, h:mm a').format(time);
  }
}

class _PriorityBadge extends StatelessWidget {
  final String priority;
  final Color color;

  const _PriorityBadge({required this.priority, required this.color});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.15),
        borderRadius: BorderRadius.circular(DJIRadius.round),
        border: Border.all(
          color: color.withValues(alpha: 0.3),
          width: 1,
        ),
      ),
      child: Text(
        priority.toUpperCase(),
        style: TextStyle(
          color: color,
          fontSize: 10,
          fontWeight: FontWeight.w600,
          letterSpacing: 0.5,
        ),
      ),
    );
  }
}
