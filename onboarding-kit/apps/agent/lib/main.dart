import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'api/health.dart';

void main() {
  runApp(const ProviderScope(child: OnboardKitAgentApp()));
}

class OnboardKitAgentApp extends StatelessWidget {
  const OnboardKitAgentApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'OnboardKit Agent',
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(seedColor: const Color(0xFF1E88E5)),
        useMaterial3: true,
      ),
      home: const HealthScreen(),
    );
  }
}

/// Phase 0 connectivity screen: confirms the app can reach the backend health
/// endpoint. Replaced by the login screen in Phase 1.
class HealthScreen extends ConsumerWidget {
  const HealthScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final health = ref.watch(healthProvider);

    return Scaffold(
      appBar: AppBar(title: const Text('OnboardKit')),
      body: Center(
        child: health.when(
          loading: () => const CircularProgressIndicator(),
          error: (error, _) => _StatusCard(
            icon: Icons.cloud_off,
            color: Colors.red,
            title: 'API unreachable',
            subtitle: '$error',
            onRetry: () => ref.invalidate(healthProvider),
          ),
          data: (status) => _StatusCard(
            icon: status.isHealthy ? Icons.check_circle : Icons.warning,
            color: status.isHealthy ? Colors.green : Colors.orange,
            title: 'API status: ${status.status}',
            subtitle: 'Database: ${status.database}',
            onRetry: () => ref.invalidate(healthProvider),
          ),
        ),
      ),
    );
  }
}

class _StatusCard extends StatelessWidget {
  const _StatusCard({
    required this.icon,
    required this.color,
    required this.title,
    required this.subtitle,
    required this.onRetry,
  });

  final IconData icon;
  final Color color;
  final String title;
  final String subtitle;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.all(24),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, color: color, size: 64),
          const SizedBox(height: 16),
          Text(title, style: Theme.of(context).textTheme.titleLarge),
          const SizedBox(height: 8),
          Text(subtitle, textAlign: TextAlign.center),
          const SizedBox(height: 24),
          FilledButton.icon(
            onPressed: onRetry,
            icon: const Icon(Icons.refresh),
            label: const Text('Retry'),
          ),
        ],
      ),
    );
  }
}
