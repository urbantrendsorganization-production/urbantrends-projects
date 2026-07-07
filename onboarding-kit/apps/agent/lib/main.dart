import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'auth/auth_controller.dart';
import 'auth/login_screen.dart';
import 'home_screen.dart';

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
      home: const _AppRoot(),
    );
  }
}

/// Swaps between login and home based on the restored/active session.
class _AppRoot extends ConsumerWidget {
  const _AppRoot();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final auth = ref.watch(authControllerProvider);
    return auth.when(
      loading: () =>
          const Scaffold(body: Center(child: CircularProgressIndicator())),
      error: (_, __) => const LoginScreen(),
      data: (session) =>
          session == null ? const LoginScreen() : HomeScreen(session: session),
    );
  }
}
