import 'package:flutter_test/flutter_test.dart';
import 'package:onboardkit_agent/api/auth.dart';

void main() {
  group('Session', () {
    test('parses a token response payload', () {
      final session = Session.fromJson(const {
        'user_id': 'u-1',
        'tenant_id': 't-1',
        'role': 'agent',
      });
      expect(session.userId, 'u-1');
      expect(session.tenantId, 't-1');
      expect(session.role, 'agent');
    });

    test('missing fields fall back to empty strings', () {
      final session = Session.fromJson(const {});
      expect(session.userId, '');
      expect(session.role, '');
    });
  });

  group('AuthException', () {
    test('stringifies to its message', () {
      expect(const AuthException('nope').toString(), 'nope');
    });
  });
}
