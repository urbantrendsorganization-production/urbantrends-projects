import 'package:flutter_test/flutter_test.dart';
import 'package:onboardkit_agent/api/health.dart';

void main() {
  group('HealthStatus', () {
    test('parses an ok payload', () {
      final status = HealthStatus.fromJson(const {
        'status': 'ok',
        'database': 'up',
      });
      expect(status.isHealthy, isTrue);
      expect(status.database, 'up');
    });

    test('degraded payload is not healthy', () {
      final status = HealthStatus.fromJson(const {
        'status': 'degraded',
        'database': 'down',
      });
      expect(status.isHealthy, isFalse);
    });

    test('missing fields fall back to unknown', () {
      final status = HealthStatus.fromJson(const {});
      expect(status.status, 'unknown');
      expect(status.database, 'unknown');
      expect(status.isHealthy, isFalse);
    });
  });
}
