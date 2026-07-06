import 'package:flutter_test/flutter_test.dart';
import 'package:onboardkit_agent/api/models.dart';
import 'package:onboardkit_agent/applications/applications_controller.dart';

void main() {
  group('AppStatus', () {
    test('maps known wire strings', () {
      expect(AppStatus.fromWire('under_review'), AppStatus.underReview);
      expect(AppStatus.fromWire('returned_for_correction'),
          AppStatus.returnedForCorrection);
    });

    test('unknown strings fall back', () {
      expect(AppStatus.fromWire('nonsense'), AppStatus.unknown);
      expect(AppStatus.fromWire(null), AppStatus.unknown);
    });

    test('editable and terminal predicates', () {
      expect(AppStatus.draft.isEditable, isTrue);
      expect(AppStatus.returnedForCorrection.isEditable, isTrue);
      expect(AppStatus.submitted.isEditable, isFalse);
      expect(AppStatus.approved.isTerminal, isTrue);
      expect(AppStatus.rejected.isTerminal, isTrue);
      expect(AppStatus.underReview.isTerminal, isFalse);
    });
  });

  group('ApplicationDetail.reviewerNotes', () {
    test('surfaces the latest return reason', () {
      final detail = ApplicationDetail.fromJson({
        'application': {
          'id': 'a1',
          'client_id': 'c1',
          'product_code': 'SAVINGS',
          'status': 'returned_for_correction',
        },
        'client': {'id': 'c1', 'full_name': 'Jane Doe'},
        'documents': const [],
        'events': [
          {'to_status': 'submitted', 'reason': null},
          {
            'to_status': 'returned_for_correction',
            'reason': 'ID photo is blurry',
          },
        ],
      });
      expect(detail.reviewerNotes, 'ID photo is blurry');
    });

    test('is null without a return event', () {
      final detail = ApplicationDetail.fromJson({
        'application': {
          'id': 'a1',
          'client_id': 'c1',
          'product_code': 'SAVINGS',
          'status': 'draft',
        },
        'client': {'id': 'c1', 'full_name': 'Jane Doe'},
        'documents': const [],
        'events': const [],
      });
      expect(detail.reviewerNotes, isNull);
    });
  });

  group('groupApplications', () {
    ApplicationSummary make(String status) => ApplicationSummary.fromJson({
          'id': 's-$status',
          'client_id': 'c1',
          'product_code': 'SAVINGS',
          'status': status,
        });

    test('buckets by status', () {
      final groups = groupApplications([
        make('draft'),
        make('returned_for_correction'),
        make('submitted'),
        make('under_review'),
        make('approved'),
        make('rejected'),
      ]);
      expect(groups[ApplicationBucket.drafts]!.length, 1);
      expect(groups[ApplicationBucket.returned]!.length, 1);
      expect(groups[ApplicationBucket.submitted]!.length, 2);
      expect(groups[ApplicationBucket.terminal]!.length, 2);
    });
  });
}
