import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'auth.dart';

/// Attaches the current access token to outgoing requests and transparently
/// refreshes it once on a `401`, replaying the original request (CLAUDE.md §7:
/// short-lived access tokens, rotating refresh tokens).
///
/// Auth endpoints are exempt: they either carry no token yet (`login`) or send
/// the refresh token in the body (`refresh`, `logout`). Refresh uses a bare Dio
/// so it never re-enters this interceptor.
class AuthInterceptor extends Interceptor {
  AuthInterceptor(this._ref, BaseOptions options)
      : _bare = Dio(BaseOptions(
          baseUrl: options.baseUrl,
          connectTimeout: options.connectTimeout,
          receiveTimeout: options.receiveTimeout,
        ));

  final Ref _ref;
  final Dio _bare;

  /// A single in-flight refresh shared by all requests that race a `401`.
  Future<bool>? _refreshing;

  static const _retriedFlag = 'auth_retried';

  bool _isAuthPath(String path) => path.contains('/auth/');

  TokenStore get _store => _ref.read(tokenStoreProvider);

  @override
  Future<void> onRequest(
    RequestOptions options,
    RequestInterceptorHandler handler,
  ) async {
    if (!_isAuthPath(options.path)) {
      final token = await _store.readAccessToken();
      if (token != null && token.isNotEmpty) {
        options.headers['Authorization'] = 'Bearer $token';
      }
    }
    handler.next(options);
  }

  @override
  Future<void> onError(
    DioException err,
    ErrorInterceptorHandler handler,
  ) async {
    final request = err.requestOptions;
    final canRetry = err.response?.statusCode == 401 &&
        !_isAuthPath(request.path) &&
        request.extra[_retriedFlag] != true;

    if (!canRetry) {
      handler.next(err);
      return;
    }

    final refreshed = await (_refreshing ??= _refresh());
    _refreshing = null;

    if (!refreshed) {
      handler.next(err);
      return;
    }

    try {
      final token = await _store.readAccessToken();
      final retryOptions = request
        ..extra[_retriedFlag] = true
        ..headers['Authorization'] = 'Bearer $token';
      final response = await _bare.fetch<dynamic>(retryOptions);
      handler.resolve(response);
    } on DioException catch (retryError) {
      handler.next(retryError);
    }
  }

  /// Exchange the stored refresh token for a fresh pair. Returns `false` when no
  /// refresh token exists or the server rejects it (the caller then surfaces the
  /// original `401`, which bounces the user to the login screen).
  Future<bool> _refresh() async {
    final refresh = await _store.readRefreshToken();
    if (refresh == null || refresh.isEmpty) return false;
    try {
      final res = await _bare.post<Map<String, dynamic>>(
        '/api/v1/auth/refresh',
        data: {'refresh_token': refresh},
      );
      final data = res.data ?? const {};
      final access = data['access_token'] as String? ?? '';
      final newRefresh = data['refresh_token'] as String? ?? '';
      if (access.isEmpty || newRefresh.isEmpty) return false;
      await _store.save(
        access: access,
        refresh: newRefresh,
        session: Session.fromJson(data),
      );
      return true;
    } on DioException {
      await _store.clear();
      return false;
    }
  }
}
