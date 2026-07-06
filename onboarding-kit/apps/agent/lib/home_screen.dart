import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';

import 'api/api_exception.dart';
import 'api/applications_repository.dart';
import 'api/auth.dart';
import 'api/models.dart';
import 'applications/applications_controller.dart';
import 'auth/auth_controller.dart';
import 'config.dart';
import 'onboarding/onboarding_screen.dart';
import 'shared/ui.dart';

/// My-applications list (CLAUDE.md §12): drafts, returned, awaiting review and
/// completed applications the agent owns. The FAB starts a new onboarding.
class HomeScreen extends ConsumerWidget {
  const HomeScreen({super.key, required this.session});

  final Session session;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final applications = ref.watch(applicationsControllerProvider);

    return Scaffold(
      appBar: AppBar(
        title: const Text('My onboardings'),
        actions: [
          IconButton(
            tooltip: 'Sign out',
            icon: const Icon(Icons.logout),
            onPressed: () => ref.read(authControllerProvider.notifier).logout(),
          ),
        ],
      ),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: () => _startOnboarding(context, ref),
        icon: const Icon(Icons.person_add),
        label: const Text('New client'),
      ),
      body: applications.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (err, _) => ErrorRetry(
          message: err is ApiException ? err.message : 'Could not load applications.',
          onRetry: () =>
              ref.read(applicationsControllerProvider.notifier).refresh(),
        ),
        data: (items) => _ApplicationsList(items: items),
      ),
    );
  }

  Future<void> _startOnboarding(BuildContext context, WidgetRef ref) async {
    final draft = await showDialog<_NewClientInput>(
      context: context,
      builder: (_) => const _NewClientDialog(),
    );
    if (draft == null || !context.mounted) return;

    // Show a blocking spinner while we create the client + draft application.
    showDialog<void>(
      context: context,
      barrierDismissible: false,
      builder: (_) => const Center(child: CircularProgressIndicator()),
    );

    final repo = ref.read(applicationsRepositoryProvider);
    try {
      final client = await repo.createClient(draft.fullName);
      final app = await repo.createApplication(
        clientId: client.id,
        productCode: draft.productCode,
      );
      if (!context.mounted) return;
      Navigator.of(context).pop(); // dismiss spinner
      await ref.read(applicationsControllerProvider.notifier).refresh();
      if (!context.mounted) return;
      await Navigator.of(context).push(
        MaterialPageRoute<void>(
          builder: (_) => OnboardingScreen(applicationId: app.id),
        ),
      );
      await ref.read(applicationsControllerProvider.notifier).refresh();
    } catch (e) {
      if (!context.mounted) return;
      Navigator.of(context).pop(); // dismiss spinner
      showErrorSnack(
        context,
        e is ApiException ? e.message : 'Could not start onboarding.',
      );
    }
  }
}

class _ApplicationsList extends ConsumerWidget {
  const _ApplicationsList({required this.items});

  final List<ApplicationSummary> items;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final groups = groupApplications(items);
    final nonEmpty = groups.entries.where((e) => e.value.isNotEmpty).toList();

    return RefreshIndicator(
      onRefresh: () =>
          ref.read(applicationsControllerProvider.notifier).refresh(),
      child: nonEmpty.isEmpty
          ? ListView(
              // Needs to scroll for RefreshIndicator to engage.
              children: const [
                SizedBox(height: 160),
                Center(
                  child: Padding(
                    padding: EdgeInsets.all(24),
                    child: Text(
                      'No onboardings yet.\nTap “New client” to begin.',
                      textAlign: TextAlign.center,
                    ),
                  ),
                ),
              ],
            )
          : ListView(
              padding: const EdgeInsets.only(bottom: 96),
              children: [
                for (final entry in nonEmpty) ...[
                  Padding(
                    padding: const EdgeInsets.fromLTRB(16, 16, 16, 4),
                    child: Text(
                      entry.key.title.toUpperCase(),
                      style: Theme.of(context).textTheme.labelSmall?.copyWith(
                            letterSpacing: 0.8,
                            color: Theme.of(context).colorScheme.outline,
                          ),
                    ),
                  ),
                  for (final app in entry.value) _ApplicationTile(app: app),
                ],
              ],
            ),
    );
  }
}

class _ApplicationTile extends ConsumerWidget {
  const _ApplicationTile({required this.app});

  final ApplicationSummary app;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final dateFmt = DateFormat('d MMM y');
    return ListTile(
      leading: CircleAvatar(
        child: Text(app.productCode.isEmpty ? '?' : app.productCode[0]),
      ),
      title: Text(app.productCode),
      subtitle: Text('Updated ${dateFmt.format(app.updatedAt)}'),
      trailing: StatusBadge(status: app.status),
      onTap: () async {
        await Navigator.of(context).push(
          MaterialPageRoute<void>(
            builder: (_) => OnboardingScreen(applicationId: app.id),
          ),
        );
        await ref.read(applicationsControllerProvider.notifier).refresh();
      },
    );
  }
}

/// Captured client name + product before the draft is created.
class _NewClientInput {
  const _NewClientInput({required this.fullName, required this.productCode});
  final String fullName;
  final String productCode;
}

class _NewClientDialog extends StatefulWidget {
  const _NewClientDialog();

  @override
  State<_NewClientDialog> createState() => _NewClientDialogState();
}

class _NewClientDialogState extends State<_NewClientDialog> {
  final _formKey = GlobalKey<FormState>();
  final _name = TextEditingController();
  String _product = AppConfig.products.first.code;

  @override
  void dispose() {
    _name.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('New client'),
      content: Form(
        key: _formKey,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            TextFormField(
              controller: _name,
              autofocus: true,
              textCapitalization: TextCapitalization.words,
              decoration: const InputDecoration(
                labelText: 'Full name',
                border: OutlineInputBorder(),
              ),
              validator: (v) =>
                  (v == null || v.trim().isEmpty) ? 'Enter a name' : null,
            ),
            const SizedBox(height: 16),
            DropdownButtonFormField<String>(
              value: _product,
              decoration: const InputDecoration(
                labelText: 'Product',
                border: OutlineInputBorder(),
              ),
              items: [
                for (final p in AppConfig.products)
                  DropdownMenuItem(value: p.code, child: Text(p.name)),
              ],
              onChanged: (v) => setState(() => _product = v ?? _product),
            ),
          ],
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(context).pop(),
          child: const Text('Cancel'),
        ),
        FilledButton(
          onPressed: () {
            if (!_formKey.currentState!.validate()) return;
            Navigator.of(context).pop(
              _NewClientInput(
                fullName: _name.text.trim(),
                productCode: _product,
              ),
            );
          },
          child: const Text('Start'),
        ),
      ],
    );
  }
}
