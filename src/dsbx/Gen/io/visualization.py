"""Visualization helpers for generated instance spaces."""

from pathlib import Path
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from loguru import logger

def plot_instance_space(summary_df: pd.DataFrame, output_path: Path) -> None:
    """
    Generates and saves an Instance Space Analysis (ISA) plot for a batch of runs.
    This version uses the correct 'target' columns for visual encoding.
    """
    if summary_df.empty:
        logger.warning("Summary data is empty, skipping instance space plot.")
        return

    # --- FIX 1: Ensure required columns exist ---
    required_cols = ['SSI_C', 'SSI_P', 'target_rho_global', 'target_ddt']
    if not all(col in summary_df.columns for col in required_cols):
        logger.error(f"Missing required columns for ISA plot. Needed: {required_cols}")
        return

    logger.info(f"Generating Instance Space plot to {output_path}...")

    # --- FIX 2: Round target values to create clean, categorical legends ---
    # This is crucial for correct grouping by color and size.
    summary_df['target_rho_global_cat'] = summary_df['target_rho_global'].round(2)
    summary_df['target_ddt_cat'] = summary_df['target_ddt'].round(2)

    fig, ax = plt.subplots(figsize=(12, 8))
    
    scatter = sns.scatterplot(
        data=summary_df,
        x='SSI_C',
        y='SSI_P',
        # --- FIX 3: Use the correct 'target' columns for encoding ---
        size='target_rho_global_cat',
        hue='target_ddt_cat',
        sizes=(100, 400), # Define a clear size range
        palette='viridis',
        ax=ax,
        alpha=0.8,
        edgecolor='w',
    )
    
    ax.set_title('Instance Space Analysis (ISA)', fontsize=16, pad=20)
    ax.set_xlabel('Congestion Stress (C)', fontsize=12)
    ax.set_ylabel('Due Date Stress (P)', fontsize=12)
    ax.grid(True, linestyle='--', alpha=0.6)
    
    ax.axvline(3.0, color='r', linestyle='--', alpha=0.5, label='High Congestion Stress (C=3)')
    ax.axhline(1.0, color='purple', linestyle='--', alpha=0.5, label='High Due Date Stress (P=1)')
    
    # Improve legend
    handles, labels = ax.get_legend_handles_labels()
    # Separate the threshold lines from the main legend
    threshold_handles = [h for h, l in zip(handles, labels) if "Stress" in l]
    threshold_labels = [l for l in labels if "Stress" in l]
    main_handles = [h for h, l in zip(handles, labels) if "Stress" not in l]
    main_labels = [l for l in labels if "Stress" not in l]
    
    ax.legend(main_handles, main_labels, bbox_to_anchor=(1.05, 1), loc='upper left', borderaxespad=0.)
    ax.add_artist(plt.legend(handles=threshold_handles, labels=threshold_labels, loc='lower right'))
    
    plt.tight_layout(rect=(0, 0, 0.85, 1))
    plt.savefig(output_path)
    plt.close(fig)
