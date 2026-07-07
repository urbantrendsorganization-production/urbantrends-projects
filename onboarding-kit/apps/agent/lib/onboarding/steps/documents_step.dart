import 'package:flutter/material.dart';
import 'package:flutter_image_compress/flutter_image_compress.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:image_picker/image_picker.dart';

import '../../api/api_exception.dart';
import '../../api/applications_repository.dart';
import '../../api/models.dart';
import '../onboarding_controller.dart';

/// Step 2 — capture the four KYC documents. Each is captured natively,
/// compressed on-device, uploaded to a presigned URL, then confirmed
/// (CLAUDE.md §11/§12). Per-doc status and retry are shown independently so one
/// failed upload never blocks the others.
class DocumentsStep extends ConsumerStatefulWidget {
  const DocumentsStep({
    super.key,
    required this.applicationId,
    required this.detail,
  });

  final String applicationId;
  final ApplicationDetail detail;

  @override
  ConsumerState<DocumentsStep> createState() => _DocumentsStepState();
}

/// Human labels for the required doc types.
const Map<String, String> _docLabels = {
  'id_front': 'ID — front',
  'id_back': 'ID — back',
  'selfie': 'Selfie',
  'address_proof': 'Proof of address',
};

class _DocumentsStepState extends ConsumerState<DocumentsStep> {
  final _picker = ImagePicker();

  /// Doc types with an upload currently in flight, and their progress/error.
  final Set<String> _busy = {};
  final Map<String, double> _progress = {};
  final Map<String, String?> _errors = {};

  OnboardingController get _controller =>
      ref.read(onboardingControllerProvider(widget.applicationId).notifier);

  ApplicationsRepository get _repo =>
      ref.read(applicationsRepositoryProvider);

  Future<void> _capture(String docType, ImageSource source) async {
    setState(() {
      _busy.add(docType);
      _errors[docType] = null;
      _progress[docType] = 0;
    });
    try {
      final picked = await _picker.pickImage(
        source: source,
        maxWidth: 2400,
        imageQuality: 90,
      );
      if (picked == null) {
        setState(() => _busy.remove(docType));
        return;
      }

      // On-device compression before upload (§12). The backend recompresses to
      // <=300KB, but shrinking here saves the agent's mobile data.
      final compressed = await FlutterImageCompress.compressWithFile(
        picked.path,
        minWidth: 1600,
        minHeight: 1600,
        quality: 80,
        format: CompressFormat.jpeg,
      );
      if (compressed == null) {
        throw const ApiException(
          message: 'Could not process the photo. Please retake it.',
        );
      }

      const contentType = 'image/jpeg';
      final presign = await _repo.presign(
        id: widget.applicationId,
        docType: docType,
        contentType: contentType,
      );
      await _repo.uploadToStorage(
        url: presign.url,
        bytes: compressed,
        contentType: contentType,
        onProgress: (sent, total) {
          if (total > 0 && mounted) {
            setState(() => _progress[docType] = sent / total);
          }
        },
      );
      await _repo.confirm(
        id: widget.applicationId,
        docType: docType,
        storageKey: presign.storageKey,
        originalFilename: picked.name,
      );
      await _controller.reload();
    } catch (e) {
      if (mounted) {
        setState(() => _errors[docType] =
            e is ApiException ? e.message : 'Upload failed. Retry.');
      }
    } finally {
      if (mounted) setState(() => _busy.remove(docType));
    }
  }

  @override
  Widget build(BuildContext context) {
    final anyProcessing = kRequiredDocTypes.any((t) {
      final d = widget.detail.documentFor(t);
      return d != null && !d.processed;
    });

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        for (final docType in kRequiredDocTypes)
          _DocCard(
            docType: docType,
            label: _docLabels[docType] ?? docType,
            document: widget.detail.documentFor(docType),
            busy: _busy.contains(docType),
            progress: _progress[docType] ?? 0,
            error: _errors[docType],
            allowGallery: docType == 'address_proof',
            onCapture: (source) => _capture(docType, source),
          ),
        if (anyProcessing) ...[
          const SizedBox(height: 8),
          Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              const Text('Some photos are still processing.'),
              TextButton(
                onPressed: () => _controller.reload(),
                child: const Text('Refresh'),
              ),
            ],
          ),
        ],
      ],
    );
  }
}

class _DocCard extends StatelessWidget {
  const _DocCard({
    required this.docType,
    required this.label,
    required this.document,
    required this.busy,
    required this.progress,
    required this.error,
    required this.allowGallery,
    required this.onCapture,
  });

  final String docType;
  final String label;
  final DocumentModel? document;
  final bool busy;
  final double progress;
  final String? error;
  final bool allowGallery;
  final ValueChanged<ImageSource> onCapture;

  @override
  Widget build(BuildContext context) {
    final ready = document?.processed ?? false;
    final processing = document != null && !document!.processed;

    return Card(
      margin: const EdgeInsets.symmetric(vertical: 6),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Row(
          children: [
            _thumbnail(context, ready),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(label,
                      style: Theme.of(context).textTheme.titleSmall),
                  const SizedBox(height: 4),
                  _statusLine(context, ready, processing),
                  if (error != null) ...[
                    const SizedBox(height: 4),
                    Text(
                      error!,
                      style: TextStyle(
                        color: Theme.of(context).colorScheme.error,
                        fontSize: 12,
                      ),
                    ),
                  ],
                ],
              ),
            ),
            _actions(context, ready),
          ],
        ),
      ),
    );
  }

  Widget _thumbnail(BuildContext context, bool ready) {
    final url = document?.thumbnailUrl ?? document?.url;
    return ClipRRect(
      borderRadius: BorderRadius.circular(8),
      child: SizedBox(
        width: 56,
        height: 56,
        child: ready && url != null
            ? Image.network(
                url,
                fit: BoxFit.cover,
                errorBuilder: (_, __, ___) => _placeholder(context),
              )
            : _placeholder(context),
      ),
    );
  }

  Widget _placeholder(BuildContext context) => Container(
        color: Theme.of(context).colorScheme.surfaceContainerHighest,
        child: Icon(
          docType == 'selfie' ? Icons.face : Icons.badge_outlined,
          color: Theme.of(context).colorScheme.outline,
        ),
      );

  Widget _statusLine(BuildContext context, bool ready, bool processing) {
    if (busy) {
      return Row(
        children: [
          SizedBox(
            width: 14,
            height: 14,
            child: CircularProgressIndicator(
              strokeWidth: 2,
              value: progress > 0 && progress < 1 ? progress : null,
            ),
          ),
          const SizedBox(width: 8),
          const Text('Uploading…'),
        ],
      );
    }
    if (ready) {
      return const Text('Ready', style: TextStyle(color: Colors.green));
    }
    if (processing) {
      return const Text('Processing…',
          style: TextStyle(color: Colors.orange));
    }
    return Text(
      'Not captured',
      style: TextStyle(color: Theme.of(context).colorScheme.outline),
    );
  }

  Widget _actions(BuildContext context, bool ready) {
    if (busy) return const SizedBox(width: 40);
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        IconButton(
          tooltip: ready ? 'Retake' : 'Capture',
          icon: Icon(ready ? Icons.refresh : Icons.camera_alt),
          onPressed: () => onCapture(ImageSource.camera),
        ),
        if (allowGallery)
          IconButton(
            tooltip: 'Pick from gallery',
            icon: const Icon(Icons.photo_library),
            onPressed: () => onCapture(ImageSource.gallery),
          ),
      ],
    );
  }
}
