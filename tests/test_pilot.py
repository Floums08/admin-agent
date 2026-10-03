"""Synthetic-only pilot-registry regressions; no network or customer data."""
import copy
import io
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

from admin_agent import pilot


class PilotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.parent = Path(self.temp.name)
        self.directory = self.parent / "pilot"

    def tearDown(self):
        self.temp.cleanup()

    def init(self, cohort="synthetic"):
        return pilot.init_pilot(self.directory, cohort, case_count=10, country="FR")

    def observation(self, case_id="case-001", status="pass"):
        result = pilot.observation_template(self.directory, case_id)
        result.update(status=status, observed_result="needs_review", reviewer_ref="reviewer-01",
                      evidence_ref="PRIVATE_EVIDENCE_LOCATION", note="PRIVATE_CLIENT_NOTE")
        result["critical_fields"] = {name: {"extraction": "correct", "review": "confirmed"} for name in pilot.CRITICAL_FIELDS}
        if status == "fail":
            result["blockers"] = ["workflow_failure"]
        return result

    def private_file(self, name, content):
        path = self.parent / name
        path.write_text(json.dumps(content), encoding="utf-8")
        path.chmod(0o600)
        return path

    def test_fresh_registry_has_no_measured_results_or_gain(self):
        self.init()
        result = pilot.report(self.directory)
        self.assertEqual(10, result["cases"]["not_tested"])
        self.assertIsNone(result["extraction"]["value_accuracy_percent"])
        self.assertIsNone(result["timing"]["paired_comparison"]["saved_seconds"])
        self.assertIsNone(result["timing"]["measurements"]["review_seconds"]["mean"])
        self.assertEqual("not_assessed", result["deployment_readiness"])
        self.assertIn("synthetic_rehearsal_is_not_client_validation", result["pending_evaluation"])

    def test_directory_and_state_are_private_and_init_never_overwrites(self):
        self.init()
        if os.name == "posix":
            self.assertEqual(0o700, stat.S_IMODE(self.directory.stat().st_mode))
            self.assertEqual(0o600, stat.S_IMODE((self.directory / "pilot.json").stat().st_mode))
        before = (self.directory / "pilot.json").read_bytes()
        with self.assertRaises(pilot.PilotError):
            self.init()
        self.assertEqual(before, (self.directory / "pilot.json").read_bytes())

    def test_case_count_and_country_are_strict(self):
        for count in (0, 9, 31, True, 10.0):
            with self.subTest(count=count), self.assertRaises(pilot.PilotError):
                pilot.init_pilot(self.directory, "synthetic", case_count=count, country="FR")
        with self.assertRaises(pilot.PilotError):
            pilot.init_pilot(self.directory, "synthetic", country="XX")

    def test_current_and_other_git_repositories_are_refused(self):
        with self.assertRaises(pilot.PilotError):
            pilot.init_pilot(Path(pilot.__file__).parents[1] / "runtime" / "private-pilot", "synthetic", country="FR")
        repo = self.parent / "other-repo"
        repo.mkdir()
        (repo / ".git").write_text("gitdir: elsewhere")
        with self.assertRaises(pilot.PilotError):
            pilot.init_pilot(repo / "pilot", "synthetic", country="FR")

    def test_real_git_directory_is_refused_but_empty_marker_is_not_a_repository(self):
        parent = self.parent / "parent"
        parent.mkdir(mode=0o700)
        marker = parent / ".git"
        marker.mkdir()
        pilot.init_pilot(parent / "allowed", "synthetic", country="FR")
        (marker / "HEAD").write_text("ref: refs/heads/main\n")
        with self.assertRaises(pilot.PilotError):
            pilot.init_pilot(parent / "refused", "synthetic", country="FR")

    def test_symlink_directory_and_file_are_refused(self):
        link = self.parent / "link"
        link.symlink_to(self.parent, target_is_directory=True)
        with self.assertRaises(pilot.PilotError):
            pilot.init_pilot(link / "pilot", "synthetic", country="FR")
        self.init()
        original = self.directory / "pilot.json"
        target = self.parent / "target.json"
        original.rename(target)
        original.symlink_to(target)
        with self.assertRaises(pilot.PilotError):
            pilot.report(self.directory)

    @unittest.skipUnless(os.name == "posix", "POSIX permission checks")
    def test_broad_permissions_are_refused(self):
        self.init()
        (self.directory / "pilot.json").chmod(0o644)
        with self.assertRaises(pilot.PilotError):
            pilot.report(self.directory)

    def test_manifest_extra_truth_never_enters_private_registry_or_reports(self):
        manifest = {"schema_version": 1, "synthetic": True, "cases": [
            {"case_id": f"synthetic-fr-{index:03}", "country": "FR", "expected_scope": "in_scope", "expected_status": "needs_review",
             "expected_fields": {"supplier": "SHOULD_NOT_COPY_PRIVATE_VALUE"}, "file": "PRIVATE_SOURCE_FILENAME.pdf"}
            for index in range(1, 11)]}
        source = self.private_file("manifest.json", manifest)
        pilot.init_pilot(self.directory, "synthetic", manifest=source)
        contents = (self.directory / "pilot.json").read_text()
        self.assertNotIn("SHOULD_NOT_COPY", contents)
        self.assertNotIn("PRIVATE_SOURCE_FILENAME", contents)
        self.assertNotIn("synthetic-fr-001", json.dumps(pilot.report(self.directory)))

    def test_synthetic_manifest_cannot_validate_client_cohort(self):
        source = self.private_file("manifest.json", {"schema_version": 1, "synthetic": True, "cases": []})
        with self.assertRaises(pilot.PilotError):
            pilot.init_pilot(self.directory, "client", manifest=source)

    def test_observation_is_versioned_and_duplicate_cannot_overwrite(self):
        self.init()
        data = self.observation()
        result = pilot.record_observation(self.directory, data)
        self.assertEqual(1, result["case_version"])
        self.assertFalse(result["outbound_executed"])
        with self.assertRaises(pilot.PilotError):
            pilot.record_observation(self.directory, data)
        self.assertEqual(1, pilot.report(self.directory)["registry_revision"])

    def test_scope_and_cohort_cannot_be_changed_by_record(self):
        self.init()
        for key, value in (("cohort", "client"), ("country", "ES"), ("expected_scope", "out_of_scope"), ("invoice_number", "PRIVATE_DATA")):
            data = self.observation()
            data[key] = value
            with self.subTest(key=key), self.assertRaises(pilot.PilotError):
                pilot.record_observation(self.directory, data)

    def test_human_evidence_and_all_ten_reviews_required_for_pass(self):
        self.init()
        for key in ("reviewer_ref", "evidence_ref"):
            data = self.observation()
            data[key] = ""
            with self.subTest(key=key), self.assertRaises(pilot.PilotError):
                pilot.record_observation(self.directory, data)
        data = self.observation()
        data["critical_fields"].pop("currency")
        with self.assertRaises(pilot.PilotError):
            pilot.record_observation(self.directory, data)

    def test_corrected_values_do_not_inflate_raw_extraction_accuracy(self):
        self.init()
        data = self.observation()
        data["critical_fields"]["total_amount"] = {"extraction": "incorrect", "review": "corrected"}
        data["critical_fields"]["supplier"] = {"extraction": "missing", "review": "corrected"}
        pilot.record_observation(self.directory, data)
        result = pilot.report(self.directory)
        self.assertEqual("80.00", result["extraction"]["value_accuracy_percent"])
        self.assertEqual("10.00", result["extraction"]["evaluation_coverage_percent"])
        self.assertEqual(2, result["review"]["corrected"])
        self.assertEqual(1, result["cases"]["pass"])

    def test_correct_abstention_is_separate_from_value_accuracy(self):
        self.init()
        data = self.observation()
        data["critical_fields"]["due_date"] = {"extraction": "correct_abstention", "review": "confirmed"}
        pilot.record_observation(self.directory, data)
        result = pilot.report(self.directory)
        self.assertEqual(9, result["extraction"]["evaluated_values"])
        self.assertEqual(1, result["extraction"]["correct_abstention"])
        self.assertEqual("100.00", result["extraction"]["value_accuracy_percent"])

    def test_unresolved_or_false_confirmation_cannot_pass(self):
        self.init()
        for extraction, review in (("incorrect", "confirmed"), ("not_tested", "confirmed"), ("correct", "corrected"), ("incorrect", "unresolved")):
            data = self.observation()
            data["critical_fields"]["total_amount"] = {"extraction": extraction, "review": review}
            with self.subTest(extraction=extraction, review=review), self.assertRaises(pilot.PilotError):
                pilot.record_observation(self.directory, data)

    def test_fail_requires_coded_blocker(self):
        self.init()
        data = self.observation(status="fail")
        data["blockers"] = []
        with self.assertRaises(pilot.PilotError):
            pilot.record_observation(self.directory, data)

    def test_estimated_negative_nonfinite_and_float_times_are_refused(self):
        self.init()
        for value in (-1, "-1", "NaN", "Infinity", 1.2, True, "100.123", "86401"):
            data = self.observation()
            data["timing"] = {"measurement": "observed", "baseline_seconds": value}
            with self.subTest(value=value), self.assertRaises(pilot.PilotError):
                pilot.record_observation(self.directory, data)
        data["timing"] = {"measurement": "estimated", "baseline_seconds": "300"}
        with self.assertRaises(pilot.PilotError):
            pilot.record_observation(self.directory, data)

    def test_unpaired_or_single_measurement_never_creates_gain(self):
        self.init()
        data = self.observation()
        data["timing"] = {"measurement": "observed", "baseline_seconds": "300", "assisted_seconds": "120"}
        pilot.record_observation(self.directory, data)
        result = pilot.report(self.directory)
        self.assertEqual(1, result["timing"]["measurements"]["assisted_seconds"]["measured_cases"])
        self.assertIsNone(result["timing"]["paired_comparison"]["saved_seconds"])
        self.assertEqual(0, result["timing"]["paired_comparison"]["cases"])

    def test_observed_matched_times_compute_exact_signed_difference(self):
        self.init()
        data = self.observation()
        data["timing"] = {"measurement": "observed", "baseline_seconds": "100", "assisted_seconds": "125.50", "review_seconds": "50.00", "correction_seconds": "20.00", "paired_comparison": True}
        pilot.record_observation(self.directory, data)
        result = pilot.report(self.directory)["timing"]
        self.assertEqual("-25.50", result["paired_comparison"]["saved_seconds"])
        self.assertEqual("-25.50", result["paired_comparison"]["saved_percent"])
        self.assertEqual("20.00", result["measurements"]["correction_seconds"]["mean"])

    def test_zero_baseline_has_no_percentage_and_missing_is_not_zero(self):
        self.init()
        data = self.observation()
        data["timing"] = {"measurement": "observed", "baseline_seconds": "0", "assisted_seconds": "20", "paired_comparison": True}
        pilot.record_observation(self.directory, data)
        result = pilot.report(self.directory)["timing"]
        self.assertEqual("-20.00", result["paired_comparison"]["saved_seconds"])
        self.assertIsNone(result["paired_comparison"]["saved_percent"])
        self.assertIsNone(result["measurements"]["correction_seconds"]["total"])

    def test_inconsistent_or_incomplete_time_pair_is_refused(self):
        self.init()
        for timing in ({"measurement": "observed", "baseline_seconds": 120, "paired_comparison": True},
                       {"measurement": "observed", "assisted_seconds": 100, "review_seconds": 101},
                       {"measurement": "observed", "review_seconds": 100, "correction_seconds": 101}):
            data = self.observation()
            data["timing"] = timing
            with self.subTest(timing=timing), self.assertRaises(pilot.PilotError):
                pilot.record_observation(self.directory, data)

    def test_report_and_csv_do_not_disclose_private_identifiers(self):
        self.init()
        pilot.record_observation(self.directory, self.observation())
        result = pilot.report(self.directory)
        serialized = json.dumps(result) + pilot.report_csv(result)
        for private in ("case-001", "reviewer-01", "PRIVATE_EVIDENCE_LOCATION", "PRIVATE_CLIENT_NOTE"):
            self.assertNotIn(private, serialized)

    def test_scope_control_and_blocked_scenario_remain_distinct_from_ready(self):
        rows = [{"case_id": f"control-{index}", "country": "FR", "expected_scope": "in_scope", "expected_status": "blocked"} for index in range(10)]
        rows[0]["expected_scope"] = "out_of_scope"
        source = self.private_file("manifest.json", {"schema_version": 1, "synthetic": True, "cases": rows})
        pilot.init_pilot(self.directory, "synthetic", manifest=source)
        data = self.observation("control-1")
        with self.assertRaises(pilot.PilotError):
            pilot.record_observation(self.directory, data)
        data["observed_result"] = "blocked"
        pilot.record_observation(self.directory, data)
        data = pilot.observation_template(self.directory, "control-0")
        data.update(status="out_of_scope", observed_result="blocked", reviewer_ref="reviewer-01", evidence_ref="private-proof", note="Multiple VAT rates, manual route.")
        for outcome in ("ready", "needs_review", "not_tested"):
            wrong = dict(data, observed_result=outcome)
            with self.subTest(outcome=outcome), self.assertRaises(pilot.PilotError):
                pilot.record_observation(self.directory, wrong)
        pilot.record_observation(self.directory, data)
        result = pilot.report(self.directory)
        self.assertEqual(1, result["cases"]["pass"])
        self.assertEqual(1, result["cases"]["out_of_scope"])
        self.assertEqual(90, result["extraction"]["eligible_critical_fields"])
        self.assertEqual("not_assessed", result["deployment_readiness"])

    def test_atomic_failure_retains_previous_registry(self):
        self.init()
        before = (self.directory / "pilot.json").read_bytes()
        with patch("admin_agent.pilot.os.replace", side_effect=OSError("PRIVATE_PATH")):
            with self.assertRaises(pilot.PilotError):
                pilot.record_observation(self.directory, self.observation())
        self.assertEqual(before, (self.directory / "pilot.json").read_bytes())
        self.assertEqual([], list(self.directory.glob(".pilot-*.tmp")))

    @unittest.skipUnless(os.name == "posix", "POSIX locking")
    def test_concurrent_writer_lock_refuses_second_writer(self):
        self.init()
        with pilot._lock(self.directory):
            with self.assertRaises(pilot.PilotError):
                pilot.record_observation(self.directory, self.observation())
        self.assertEqual(0, pilot.report(self.directory)["registry_revision"])

    def test_cli_template_record_report_and_refusal_do_not_print_private_data(self):
        output = io.StringIO()
        with patch("sys.stdout", output):
            self.assertEqual(0, pilot.main(["init", "--directory", str(self.directory), "--cohort", "client", "--country", "ES", "--cases", "10"]))
        template = self.parent / "observation.json"
        with patch("sys.stdout", io.StringIO()):
            self.assertEqual(0, pilot.main(["template", "--directory", str(self.directory), "--case", "case-001", "--output", str(template)]))
        template.write_text(json.dumps(self.observation()), encoding="utf-8")
        output = io.StringIO()
        with patch("sys.stdout", output):
            self.assertEqual(0, pilot.main(["record", "--directory", str(self.directory), "--record", str(template)]))
            self.assertEqual(0, pilot.main(["report", "--directory", str(self.directory), "--format", "csv"]))
        self.assertNotIn("PRIVATE", output.getvalue())
        error = io.StringIO()
        with patch("sys.stderr", error):
            self.assertEqual(2, pilot.main(["record", "--directory", str(self.directory), "--record", str(self.parent / "PRIVATE_MISSING.json")]))
        self.assertNotIn("PRIVATE_MISSING", error.getvalue())

    def test_export_files_never_overwrite_existing_content(self):
        self.init()
        output = self.private_file("report.json", {"preserve": True})
        with patch("sys.stderr", io.StringIO()):
            code = pilot.main(["report", "--directory", str(self.directory), "--output", str(output)])
        self.assertEqual(2, code)
        self.assertEqual({"preserve": True}, json.loads(output.read_text()))

    def test_manually_corrupted_registry_is_controlled(self):
        self.init()
        path = self.directory / "pilot.json"
        state = json.loads(path.read_text())
        state["cases"][0].pop("critical_fields")
        path.write_text(json.dumps(state), encoding="utf-8")
        with self.assertRaises(pilot.PilotError):
            pilot.report(self.directory)

    @unittest.skipUnless(hasattr(os, "mkfifo"), "POSIX FIFOs")
    def test_fifo_input_is_refused_without_waiting_for_a_writer(self):
        fifo = self.parent / "pipe"
        os.mkfifo(fifo, 0o600)
        with self.assertRaises(pilot.PilotError):
            pilot._read(fifo)


if __name__ == "__main__":
    unittest.main()
