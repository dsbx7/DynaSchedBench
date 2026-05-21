"""Configuration migration helpers for DynaSchedBench input files."""
# Configuration migration tool for backward compatibility

import copy
from typing import Dict, Any
from loguru import logger


class ConfigMigrator:
    """Migrate legacy configuration files to the current schema.

    The v1.0 to v2.0 migration moves horizon into ``Scale``, initial WIP into
    ``EvaluationConfig``, adds ``Dynamics``, and places job-mix weights under
    ``Plant``.
    """
    
    @staticmethod
    def migrate_v1_to_v2(old_config: dict) -> dict:
        """Migrate a v1.0 configuration dictionary to the v2.0 layered schema.

        Args:
            old_config: Configuration dictionary in v1.0 format.

        Returns:
            Configuration dictionary in v2.0 format.
        """
        new_config = copy.deepcopy(old_config)
        
        logger.info("Starting configuration migration: v1.0 → v2.0")
        
        if 'meta' in new_config and 'horizon' in new_config['meta']:
            horizon = new_config['meta'].pop('horizon')
            if 'scale' not in new_config:
                new_config['scale'] = {}
            new_config['scale']['horizon'] = horizon
            logger.debug(f"Meta.horizon ({horizon}) migrated to Scale.horizon")
        
        if 'scale' in new_config and 'n0_initial' in new_config['scale']:
            n0 = new_config['scale'].pop('n0_initial')
            if 'evaluation' not in new_config:
                new_config['evaluation'] = {}
            new_config['evaluation']['n0_initial'] = n0
            logger.debug(
                f"Scale.n0_initial ({n0}) migrated to EvaluationConfig.n0_initial"
            )
        
        if 'targets' in new_config and 'job_mix_weights' in new_config['targets']:
            weights = new_config['targets'].pop('job_mix_weights')
            if 'plant' not in new_config:
                logger.error(
                    "Cannot migrate job_mix_weights: 'plant' configuration is missing"
                )
            else:
                new_config['plant']['job_mix_weights'] = weights
                logger.debug("Targets.job_mix_weights migrated to Plant.job_mix_weights")
        
        dynamics_config = {}
        if 'targets' in new_config:
            for key in ['arrival_pattern', 'arrival_amplitude', 'arrival_period']:
                if key in new_config['targets']:
                    dynamics_config[key] = new_config['targets'].pop(key)
                    logger.debug(f"Targets.{key} migrated to Dynamics.{key}")
        
        if not dynamics_config:
            dynamics_config = {
                'arrival_pattern': 'constant',
                'arrival_amplitude': 0.0,
                'arrival_period': None
            }
        
        new_config['dynamics'] = dynamics_config
        
        if 'meta' not in new_config:
            new_config['meta'] = {}
        new_config['meta']['version'] = '2.0'
        logger.debug("Configuration version updated to 2.0")
        
        logger.info("Configuration migration completed: v1.0 → v2.0 (four-layer architecture)")
        return new_config
    
    @staticmethod
    def detect_version(config: dict) -> str:
        """Detect the configuration-file version.

        Args:
            config: Configuration dictionary.

        Returns:
            Version string: '1.0', '2.0', or 'unknown'.
        """
        if 'meta' in config and 'version' in config['meta']:
            version = config['meta']['version']
            if version in ['1.0', '1', 'v1.0', 'v1']:
                return '1.0'
            elif version in ['2.0', '2', 'v2.0', 'v2']:
                return '2.0'
            return version
        
        if 'dynamics' in config:
            return '2.0'
        
        if 'scale' in config and 'horizon' in config['scale']:
            return '2.0'
        
        if 'meta' in config and 'horizon' in config['meta']:
            return '1.0'
        
        if 'scale' in config and 'n0_initial' in config['scale']:
            return '1.0'
        
        logger.warning(
            "Could not determine configuration version; assuming v1.0 by default"
        )
        return '1.0'
    
    @staticmethod
    def migrate_if_needed(config: dict) -> dict:
        """Detect the version and migrate the configuration if needed.

        Args:
            config: Raw configuration dictionary.

        Returns:
            Configuration dictionary, migrated when required.
        """
        version = ConfigMigrator.detect_version(config)
        
        if version == '1.0':
            logger.info("Detected v1.0 configuration; migrating to v2.0")
            return ConfigMigrator.migrate_v1_to_v2(config)
        elif version == '2.0':
            logger.debug("Configuration is already v2.0; no migration needed")
            return config
        else:
            logger.warning(
                f"Unknown configuration version: {version}; attempting to parse as v2.0"
            )
            return config


















