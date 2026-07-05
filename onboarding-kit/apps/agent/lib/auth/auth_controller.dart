import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../api/auth.dart';

/// Owns the current [Session] (or `null` when signed out) and drives login /
/// logout. On startup it restores any persisted session from secure storage.
class AuthController extends AsyncNotifier<Session?> {
  @override
  Future<Session?> build() async {
    final store = ref.watch(tokenStoreProvider);
    // A persisted access token means a session; the session claims are cached
    // alongside it. (Token refresh/validation against /me lands in Phase 2.)
    final token = await store.readAccessToken();
    if (token == null) return null;
    return store.readSession();
  }

  Future<void> login(String email, String password) async {
    state = const AsyncLoading();
    state = await AsyncValue.guard(
      () => ref.read(authRepositoryProvider).login(email, password),
    );
  }

  Future<void> logout() async {
    await ref.read(authRepositoryProvider).logout();
    state = const AsyncData(null);
  }
}

final authControllerProvider =
    AsyncNotifierProvider<AuthController, Session?>(AuthController.new);
