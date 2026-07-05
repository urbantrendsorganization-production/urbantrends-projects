import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'api/auth.dart';
import 'auth/auth_controller.dart';

/// Signed-in landing screen. Phase 1 confirms the session; the applications list
/// and onboarding stepper land in Phase 2 (CLAUDE.md §12).
class HomeScreen extends ConsumerWidget {
  const HomeScreen({super.key, required this.session});

  final Session session;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('OnboardKit'),
        actions: [
          IconButton(
            tooltip: 'Sign out',
            icon: const Icon(Icons.logout),
            onPressed: () => ref.read(authControllerProvider.notifier).logout(),
          ),
        ],
      ),
      body: Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(Icons.verified_user, size: 64, color: Colors.green),
            const SizedBox(height: 16),
            Text(
              'Signed in as ${session.role}',
              style: Theme.of(context).textTheme.titleLarge,
            ),
            const SizedBox(height: 8),
            const Text('Your applications will appear here in Phase 2.'),
          ],
        ),
      ),
    );
  }
}
