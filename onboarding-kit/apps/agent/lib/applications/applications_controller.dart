import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../api/applications_repository.dart';
import '../api/models.dart';

/// Loads and refreshes the agent's applications queue (`GET /applications`).
///
/// The onboarding flow invalidates this after each create/submit so the list
/// reflects reality without a manual pull-to-refresh.
class ApplicationsController extends AsyncNotifier<List<ApplicationSummary>> {
  @override
  Future<List<ApplicationSummary>> build() async {
    final page = await ref.watch(applicationsRepositoryProvider).list();
    return page.items;
  }

  /// Re-fetch, surfacing errors through the async state (never throws).
  Future<void> refresh() async {
    state = const AsyncLoading();
    state = await AsyncValue.guard(() async {
      final page = await ref.read(applicationsRepositoryProvider).list();
      return page.items;
    });
  }
}

final applicationsControllerProvider =
    AsyncNotifierProvider<ApplicationsController, List<ApplicationSummary>>(
  ApplicationsController.new,
);

/// The four buckets shown on the list screen (CLAUDE.md §12).
enum ApplicationBucket {
  drafts('In progress'),
  returned('Returned for correction'),
  submitted('Awaiting review'),
  terminal('Completed');

  const ApplicationBucket(this.title);
  final String title;
}

/// Group summaries into display buckets, newest first within each.
Map<ApplicationBucket, List<ApplicationSummary>> groupApplications(
  List<ApplicationSummary> items,
) {
  final groups = <ApplicationBucket, List<ApplicationSummary>>{
    for (final b in ApplicationBucket.values) b: <ApplicationSummary>[],
  };
  for (final a in items) {
    final bucket = switch (a.status) {
      AppStatus.draft => ApplicationBucket.drafts,
      AppStatus.returnedForCorrection => ApplicationBucket.returned,
      AppStatus.submitted || AppStatus.underReview => ApplicationBucket.submitted,
      AppStatus.approved || AppStatus.rejected => ApplicationBucket.terminal,
      AppStatus.unknown => ApplicationBucket.submitted,
    };
    groups[bucket]!.add(a);
  }
  for (final list in groups.values) {
    list.sort((a, b) => b.updatedAt.compareTo(a.updatedAt));
  }
  return groups;
}
