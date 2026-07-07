import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import 'health.dart' show dioProvider;

/// The authenticated session (non-sensitive claims), mirrored from the token
/// response. Tokens themselves are kept only in secure storage.
class Session {
  const Session({
    required this.userId,
    required this.tenantId,
    required this.role,
  });

  final String userId;
  final String tenantId;
  final String role;

  factory Session.fromJson(Map<String, dynamic> json) => Session(
        userId: json['user_id'] as String? ?? '',
        tenantId: json['tenant_id'] as String? ?? '',
        role: json['role'] as String? ?? '',
      );
}

/// Raised on a failed authentication attempt. Message is safe to show.
class AuthException implements Exception {
  const AuthException(this.message);
  final String message;
  @override
  String toString() => message;
}

/// Secure token + session persistence (CLAUDE.md §12: `flutter_secure_storage`).
class TokenStore {
  const TokenStore(this._storage);

  final FlutterSecureStorage _storage;

  static const _access = 'access_token';
  static const _refresh = 'refresh_token';
  static const _userId = 'user_id';
  static const _tenantId = 'tenant_id';
  static const _role = 'role';

  Future<void> save({
    required String access,
    required String refresh,
    required Session session,
  }) async {
    await _storage.write(key: _access, value: access);
    await _storage.write(key: _refresh, value: refresh);
    await _storage.write(key: _userId, value: session.userId);
    await _storage.write(key: _tenantId, value: session.tenantId);
    await _storage.write(key: _role, value: session.role);
  }

  Future<String?> readAccessToken() => _storage.read(key: _access);
  Future<String?> readRefreshToken() => _storage.read(key: _refresh);

  Future<Session?> readSession() async {
    final userId = await _storage.read(key: _userId);
    final tenantId = await _storage.read(key: _tenantId);
    final role = await _storage.read(key: _role);
    if (userId == null || tenantId == null || role == null) return null;
    return Session(userId: userId, tenantId: tenantId, role: role);
  }

  Future<void> clear() async {
    await _storage.deleteAll();
  }
}

/// Talks to the auth endpoints and persists tokens on success.
class AuthRepository {
  const AuthRepository(this._dio, this._store);

  final Dio _dio;
  final TokenStore _store;

  /// Log in and persist the returned tokens + session.
  ///
  /// Throws [AuthException] on bad credentials or an unreachable API.
  Future<Session> login(String email, String password) async {
    try {
      final res = await _dio.post<Map<String, dynamic>>(
        '/api/v1/auth/login',
        data: {'email': email, 'password': password},
      );
      final data = res.data ?? const {};
      final session = Session.fromJson(data);
      await _store.save(
        access: data['access_token'] as String? ?? '',
        refresh: data['refresh_token'] as String? ?? '',
        session: session,
      );
      return session;
    } on DioException catch (e) {
      if (e.response?.statusCode == 401) {
        throw const AuthException('Invalid email or password.');
      }
      throw const AuthException('Could not reach the server. Try again.');
    }
  }

  /// Best-effort logout: revoke the refresh token, then clear local storage.
  Future<void> logout() async {
    final refresh = await _store.readRefreshToken();
    if (refresh != null) {
      try {
        await _dio.post<void>(
          '/api/v1/auth/logout',
          data: {'refresh_token': refresh},
        );
      } on DioException {
        // Ignore; we clear local tokens regardless.
      }
    }
    await _store.clear();
  }
}

final secureStorageProvider = Provider<FlutterSecureStorage>((ref) {
  return const FlutterSecureStorage(
    aOptions: AndroidOptions(encryptedSharedPreferences: true),
  );
});

final tokenStoreProvider = Provider<TokenStore>((ref) {
  return TokenStore(ref.watch(secureStorageProvider));
});

final authRepositoryProvider = Provider<AuthRepository>((ref) {
  return AuthRepository(ref.watch(dioProvider), ref.watch(tokenStoreProvider));
});
