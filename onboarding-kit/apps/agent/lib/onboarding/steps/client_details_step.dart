import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';

import '../../api/api_exception.dart';
import '../../api/models.dart';
import '../../shared/ui.dart';
import '../onboarding_controller.dart';

/// Step 1 — client personal details with progressive PATCH save per sub-section
/// (CLAUDE.md §12: a dropped connection must never lose work, so personal
/// details and next-of-kin persist independently).
class ClientDetailsStep extends ConsumerStatefulWidget {
  const ClientDetailsStep({
    super.key,
    required this.applicationId,
    required this.detail,
  });

  final String applicationId;
  final ApplicationDetail detail;

  @override
  ConsumerState<ClientDetailsStep> createState() => _ClientDetailsStepState();
}

class _ClientDetailsStepState extends ConsumerState<ClientDetailsStep> {
  late final TextEditingController _fullName;
  late final TextEditingController _phone;
  late final TextEditingController _nationalId;
  late final TextEditingController _kraPin;
  late final TextEditingController _address;
  late final TextEditingController _kinName;
  late final TextEditingController _kinPhone;
  late final TextEditingController _kinRelationship;
  DateTime? _dob;

  bool _savingPersonal = false;
  bool _savingKin = false;

  @override
  void initState() {
    super.initState();
    final c = widget.detail.client;
    _fullName = TextEditingController(text: c.fullName);
    _phone = TextEditingController(text: c.phone ?? '');
    _nationalId = TextEditingController(text: c.nationalIdNumber ?? '');
    _kraPin = TextEditingController(text: c.kraPin ?? '');
    _address = TextEditingController(text: c.address ?? '');
    _kinName = TextEditingController(text: c.nextOfKinName ?? '');
    _kinPhone = TextEditingController(text: c.nextOfKinPhone ?? '');
    _kinRelationship =
        TextEditingController(text: c.nextOfKinRelationship ?? '');
    _dob = c.dateOfBirth;
  }

  @override
  void dispose() {
    _fullName.dispose();
    _phone.dispose();
    _nationalId.dispose();
    _kraPin.dispose();
    _address.dispose();
    _kinName.dispose();
    _kinPhone.dispose();
    _kinRelationship.dispose();
    super.dispose();
  }

  OnboardingController get _controller =>
      ref.read(onboardingControllerProvider(widget.applicationId).notifier);

  Future<void> _savePersonal() async {
    if (_fullName.text.trim().isEmpty) {
      showErrorSnack(context, 'A full name is required.');
      return;
    }
    setState(() => _savingPersonal = true);
    try {
      await _controller.saveSection(
        fullName: _fullName.text.trim(),
        phone: _phone.text.trim(),
        nationalIdNumber: _nationalId.text.trim(),
        kraPin: _kraPin.text.trim(),
        dateOfBirth: _dob,
        address: _address.text.trim(),
      );
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Personal details saved.')),
        );
      }
    } catch (e) {
      if (mounted) {
        showErrorSnack(
          context,
          e is ApiException ? e.message : 'Could not save. Try again.',
        );
      }
    } finally {
      if (mounted) setState(() => _savingPersonal = false);
    }
  }

  Future<void> _saveKin() async {
    setState(() => _savingKin = true);
    try {
      await _controller.saveSection(
        nextOfKin: {
          'name': _kinName.text.trim(),
          'phone': _kinPhone.text.trim(),
          'relationship': _kinRelationship.text.trim(),
        },
      );
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Next of kin saved.')),
        );
      }
    } catch (e) {
      if (mounted) {
        showErrorSnack(
          context,
          e is ApiException ? e.message : 'Could not save. Try again.',
        );
      }
    } finally {
      if (mounted) setState(() => _savingKin = false);
    }
  }

  Future<void> _pickDob() async {
    final now = DateTime.now();
    final picked = await showDatePicker(
      context: context,
      initialDate: _dob ?? DateTime(now.year - 30),
      firstDate: DateTime(now.year - 100),
      lastDate: now,
    );
    if (picked != null) setState(() => _dob = picked);
  }

  @override
  Widget build(BuildContext context) {
    final dobLabel =
        _dob == null ? 'Select date' : DateFormat('d MMM y').format(_dob!);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        _field(_fullName, 'Full name', TextInputType.name),
        _field(_phone, 'Phone (client)', TextInputType.phone,
            hint: '+254 7XX XXX XXX'),
        _field(_nationalId, 'National ID number', TextInputType.number),
        _field(_kraPin, 'KRA PIN (optional)', TextInputType.text),
        const SizedBox(height: 12),
        InkWell(
          onTap: _pickDob,
          child: InputDecorator(
            decoration: const InputDecoration(
              labelText: 'Date of birth',
              border: OutlineInputBorder(),
            ),
            child: Text(dobLabel),
          ),
        ),
        const SizedBox(height: 12),
        _field(_address, 'Address', TextInputType.streetAddress, maxLines: 2),
        const SizedBox(height: 8),
        _saveButton(
          label: 'Save personal details',
          busy: _savingPersonal,
          onPressed: _savePersonal,
        ),
        const Divider(height: 32),
        Text('Next of kin', style: Theme.of(context).textTheme.titleSmall),
        const SizedBox(height: 8),
        _field(_kinName, 'Name', TextInputType.name),
        _field(_kinPhone, 'Phone', TextInputType.phone),
        _field(_kinRelationship, 'Relationship', TextInputType.text),
        const SizedBox(height: 8),
        _saveButton(
          label: 'Save next of kin',
          busy: _savingKin,
          onPressed: _saveKin,
        ),
      ],
    );
  }

  Widget _field(
    TextEditingController controller,
    String label,
    TextInputType keyboard, {
    String? hint,
    int maxLines = 1,
  }) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: TextField(
        controller: controller,
        keyboardType: keyboard,
        maxLines: maxLines,
        decoration: InputDecoration(
          labelText: label,
          hintText: hint,
          border: const OutlineInputBorder(),
        ),
      ),
    );
  }

  Widget _saveButton({
    required String label,
    required bool busy,
    required VoidCallback onPressed,
  }) {
    return FilledButton.tonal(
      onPressed: busy ? null : onPressed,
      child: busy
          ? const SizedBox(
              height: 18,
              width: 18,
              child: CircularProgressIndicator(strokeWidth: 2),
            )
          : Text(label),
    );
  }
}
