"""Tests for lazy loading configuration system."""

import json
import os
from pathlib import Path

import pytest

from browser_use.config import CONFIG, load_and_migrate_config


class TestConfigFileLoading:
	"""Test that configuration loading preserves invalid files."""

	def test_invalid_json_preserves_config_file(self, tmp_path):
		"""Do not replace a corrupt config file with permissive defaults."""
		config_path = tmp_path / 'config.json'
		config_contents = '{"browser_profile":{"default":{"allowed_domains":["example.com"]}}'
		config_path.write_text(config_contents, encoding='utf-8')

		with pytest.raises(json.JSONDecodeError):
			load_and_migrate_config(config_path)

		assert config_path.read_text(encoding='utf-8') == config_contents

	@pytest.mark.parametrize(
		'config_data',
		[
			{'browser_profile': {'default': {'allowed_domains': ['example.com']}}, 'llm': {}, 'agent': {}},
			{'browser_profile': {'default': {'allowed_domains': ['example.com']}}},
			{'browser_profile': {}, 'llm': {}, 'agent': {}},
			{'legacy': {'allowed_domains': ['example.com']}},
			[],
		],
	)
	def test_unrecognized_config_never_overwrites_existing_file(self, tmp_path, config_data):
		config_path = tmp_path / 'config.json'
		contents = json.dumps(config_data)
		config_path.write_text(contents, encoding='utf-8')

		with pytest.raises((ValueError, TypeError)):
			load_and_migrate_config(config_path)

		assert config_path.read_text(encoding='utf-8') == contents

	def test_valid_config_is_read_without_modification(self, tmp_path):
		config_path = tmp_path / 'config.json'
		contents = json.dumps(
			{
				'browser_profile': {'profile-1': {'id': 'profile-1', 'allowed_domains': ['example.com']}},
				'llm': {},
				'agent': {},
			}
		)
		config_path.write_text(contents, encoding='utf-8')

		result = load_and_migrate_config(config_path)

		assert result.browser_profile['profile-1'].allowed_domains == ['example.com']
		assert config_path.read_text(encoding='utf-8') == contents

	def test_missing_config_is_created(self, tmp_path):
		config_path = tmp_path / 'new' / 'config.json'
		result = load_and_migrate_config(config_path)
		assert config_path.is_file()
		assert result.browser_profile
		assert json.loads(config_path.read_text(encoding='utf-8'))['browser_profile']

	def test_file_created_after_existence_check_is_not_overwritten(self, tmp_path, monkeypatch):
		config_path = tmp_path / 'config.json'
		contents = '{"created": "by another process"}'
		config_path.write_text(contents, encoding='utf-8')
		original_exists = Path.exists

		def stale_exists(path):
			return False if path == config_path else original_exists(path)

		monkeypatch.setattr(Path, 'exists', stale_exists)
		with pytest.raises(FileExistsError):
			load_and_migrate_config(config_path)
		assert config_path.read_text(encoding='utf-8') == contents


class TestLazyConfig:
	"""Test lazy loading of environment variables through CONFIG object."""

	def test_config_reads_env_vars_lazily(self):
		"""Test that CONFIG reads environment variables each time they're accessed."""
		# Set an env var
		original_value = os.environ.get('BROWSER_USE_LOGGING_LEVEL', '')
		try:
			os.environ['BROWSER_USE_LOGGING_LEVEL'] = 'debug'
			assert CONFIG.BROWSER_USE_LOGGING_LEVEL == 'debug'

			# Change the env var
			os.environ['BROWSER_USE_LOGGING_LEVEL'] = 'info'
			assert CONFIG.BROWSER_USE_LOGGING_LEVEL == 'info'

			# Delete the env var to test default
			del os.environ['BROWSER_USE_LOGGING_LEVEL']
			assert CONFIG.BROWSER_USE_LOGGING_LEVEL == 'info'  # default value
		finally:
			# Restore original value
			if original_value:
				os.environ['BROWSER_USE_LOGGING_LEVEL'] = original_value
			else:
				os.environ.pop('BROWSER_USE_LOGGING_LEVEL', None)

	def test_boolean_env_vars(self):
		"""Test boolean environment variables are parsed correctly."""
		original_value = os.environ.get('ANONYMIZED_TELEMETRY', '')
		try:
			# Test true values
			for true_val in ['true', 'True', 'TRUE', 'yes', 'Yes', '1']:
				os.environ['ANONYMIZED_TELEMETRY'] = true_val
				assert CONFIG.ANONYMIZED_TELEMETRY is True, f'Failed for value: {true_val}'

			# Test false values
			for false_val in ['false', 'False', 'FALSE', 'no', 'No', '0']:
				os.environ['ANONYMIZED_TELEMETRY'] = false_val
				assert CONFIG.ANONYMIZED_TELEMETRY is False, f'Failed for value: {false_val}'
		finally:
			if original_value:
				os.environ['ANONYMIZED_TELEMETRY'] = original_value
			else:
				os.environ.pop('ANONYMIZED_TELEMETRY', None)

	def test_api_keys_lazy_loading(self):
		"""Test API keys are loaded lazily."""
		original_value = os.environ.get('OPENAI_API_KEY', '')
		try:
			# Test empty default
			os.environ.pop('OPENAI_API_KEY', None)
			assert CONFIG.OPENAI_API_KEY == ''

			# Set a value
			os.environ['OPENAI_API_KEY'] = 'test-key-123'
			assert CONFIG.OPENAI_API_KEY == 'test-key-123'

			# Change the value
			os.environ['OPENAI_API_KEY'] = 'new-key-456'
			assert CONFIG.OPENAI_API_KEY == 'new-key-456'
		finally:
			if original_value:
				os.environ['OPENAI_API_KEY'] = original_value
			else:
				os.environ.pop('OPENAI_API_KEY', None)

	def test_path_configuration(self):
		"""Test path configuration variables."""
		original_value = os.environ.get('XDG_CACHE_HOME', '')
		try:
			# Test custom path
			test_path = '/tmp/test-cache'
			os.environ['XDG_CACHE_HOME'] = test_path
			# Use Path().resolve() to handle symlinks (e.g., /tmp -> /private/tmp on macOS)
			from pathlib import Path

			assert CONFIG.XDG_CACHE_HOME == Path(test_path).resolve()

			# Test default path expansion
			os.environ.pop('XDG_CACHE_HOME', None)
			assert '/.cache' in str(CONFIG.XDG_CACHE_HOME)
		finally:
			if original_value:
				os.environ['XDG_CACHE_HOME'] = original_value
			else:
				os.environ.pop('XDG_CACHE_HOME', None)

	def test_cloud_sync_inherits_telemetry(self):
		"""Test BROWSER_USE_CLOUD_SYNC inherits from ANONYMIZED_TELEMETRY when not set."""
		telemetry_original = os.environ.get('ANONYMIZED_TELEMETRY', '')
		sync_original = os.environ.get('BROWSER_USE_CLOUD_SYNC', '')
		try:
			# When BROWSER_USE_CLOUD_SYNC is not set, it should inherit from ANONYMIZED_TELEMETRY
			os.environ['ANONYMIZED_TELEMETRY'] = 'true'
			os.environ.pop('BROWSER_USE_CLOUD_SYNC', None)
			assert CONFIG.BROWSER_USE_CLOUD_SYNC is True

			os.environ['ANONYMIZED_TELEMETRY'] = 'false'
			os.environ.pop('BROWSER_USE_CLOUD_SYNC', None)
			assert CONFIG.BROWSER_USE_CLOUD_SYNC is False

			# When explicitly set, it should use its own value
			os.environ['ANONYMIZED_TELEMETRY'] = 'false'
			os.environ['BROWSER_USE_CLOUD_SYNC'] = 'true'
			assert CONFIG.BROWSER_USE_CLOUD_SYNC is True
		finally:
			if telemetry_original:
				os.environ['ANONYMIZED_TELEMETRY'] = telemetry_original
			else:
				os.environ.pop('ANONYMIZED_TELEMETRY', None)
			if sync_original:
				os.environ['BROWSER_USE_CLOUD_SYNC'] = sync_original
			else:
				os.environ.pop('BROWSER_USE_CLOUD_SYNC', None)
