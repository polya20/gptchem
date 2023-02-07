# Start with a random sample 100 SMILES to train the first model
# Then, generate 100 SMILES from distribution with mean shifted by 1 eV
# Train a new model on the SMILES that have HOMO LUMO gap greater than old mean + 0.5 eV
# Repeat until the mean is greater than 5.5 eV
from pathlib import Path

from fastcore.all import L
from fastcore.xtras import save_pickle
from loguru import logger
import pandas as pd
import numpy as np
from gptchem.data import get_qmug_small_data
from gptchem.evaluator import evaluate_homo_lumo_gap, is_valid
from gptchem.extractor import InverseExtractor
from gptchem.formatter import InverseDesignFormatter
from gptchem.querier import Querier
from gptchem.tuner import Tuner

TEMPERATURES = [0.0, 0.1, 0.2, 0.5, 0.75, 1.0, 1.25, 1.5]
NUM_SAMPLES = [100, 50, 500]


def make_input_frame(smiles, gaps):
    input_data = []
    for smile, gap in zip(smiles, gaps):
        input_data.append({"smiles": smile, "gap": gap})
    input_df = pd.DataFrame(input_data)

    formatter = InverseDesignFormatter(
        representation_column="smiles",
        property_columns=["gap"],
        property_names=["bandgap"],
        num_digits=1,
    )
    formatted = formatter(input_df)

    return input_df, formatted


def train(smiles, gaps):
    input_df, formatted = make_input_frame(smiles, gaps)

    tuner = Tuner(n_epochs=8, learning_rate_multiplier=0.02, wandb_sync=False)
    tune_res = tuner(formatted)
    return formatted, tune_res


def generate_desired_dist(mean: float = 5.0, width: float = 0.2, num_points: int = 100):
    return np.random.normal(mean, width, size=num_points)


def select_relevant_smiles_and_gaps(smile_gap_frame, current_mean, minimum_step: float = 1):
    subset = smile_gap_frame[smile_gap_frame["gap"] > current_mean + minimum_step]
    relevant_smiles = subset["smiles"].tolist()
    relevant_gaps = subset["gap"].tolist()
    return relevant_smiles, relevant_gaps


def sample_across_temperatures(
    tune_res,
    mean: float = 5.0,
    width: float = 0.2,
    num_points: int = 100,
):
    querier = Querier(tune_res["model_name"], max_tokens=600)
    extractor = InverseExtractor()
    generated = []

    temp_res = []
    desired_gaps = generate_desired_dist(mean, width, num_points)
    df, formatted = make_input_frame(["smiles"] * len(desired_gaps), desired_gaps)
    for temp in TEMPERATURES:
        try:
            logger.info(f"Temperature: {temp}")
            completions = querier(formatted, temperature=temp)
            generated_smiles = extractor(completions)
            logger.info(f"Extracted. Evaluating generated SMILES...")
            logger.info(f"generated examples {generated_smiles[:2]}")
            valid_smiles, valid_indices, valid_desires = [], [], []

            for i, smile in enumerate(generated_smiles):
                if is_valid(smile):
                    valid_smiles.append(smile)
                    valid_indices.append(i)
                    valid_desires.append(desired_gaps[i])

            logger.info(f"Valid SMILES: {valid_smiles[:2]}")
            evaluation_res = evaluate_homo_lumo_gap(
                valid_smiles,
                valid_desires,
            )
            found_gaps = evaluation_res["computed_gaps"]
            for smile, gap in zip(valid_smiles, found_gaps):
                generated.append({"smiles": smile, "gap": gap})

            temp_res.append(
                {
                    "temperature": temp,
                    "generated_smiles": generated_smiles,
                    "valid_smiles": valid_smiles,
                    "valid_indices": valid_indices,
                    "valid_desires": valid_desires,
                    "evaluation_res": evaluation_res,
                }
            )

        except Exception as e:
            logger.exception(e)
            continue

    generated_df = pd.DataFrame(generated)
    return generated_df, temp_res


def main(
    num_samples: int = 100, target_mean: float = 5.5, minimum_step: float = 1.0, max_iter: int = 10
):
    iter_counter = 0
    results = []
    input_data = get_qmug_small_data()
    subset = input_data.sample(num_samples)
    smiles = subset["SMILES"].tolist()
    gaps = subset["GFN2_HOMO_LUMO_GAP_mean_ev"].tolist()

    current_mean = np.mean(gaps)
    logger.info(f"Current mean: {current_mean}")

    while current_mean < target_mean and iter_counter < max_iter:
        minimum_step_ = minimum_step
        logger.info(f"Iteration {iter_counter}")
        formatted, tune_res = train(smiles, gaps)
        generated_df, temp_res = sample_across_temperatures(tune_res, current_mean)
        relevant_smiles, relevant_gaps = select_relevant_smiles_and_gaps(
            generated_df, current_mean, minimum_step
        )
        while len(relevant_smiles) == 0:
            minimum_step_ = minimum_step / 2
            logger.info("No relevant SMILES found. Lowering minimum step.")
            relevant_smiles, relevant_gaps = select_relevant_smiles_and_gaps(
                generated_df, current_mean, minimum_step_
            )

        logger.info(f"Relevant SMILES: {relevant_smiles[:2]}")
        logger.info(f"Relevant GAPS: {relevant_gaps[:2]}")
        current_mean = np.mean(relevant_gaps)
        logger.info(f"New mean: {current_mean}")
        smiles = relevant_smiles
        gaps = relevant_gaps
        results.append(
            {
                "iteration": iter_counter,
                "formatted": formatted,
                "tune_res": tune_res,
                "generated_df": generated_df,
                "temp_res": temp_res,
                "relevant_smiles": relevant_smiles,
                "relevant_gaps": relevant_gaps,
                "current_mean": current_mean,
                "minimum_step": minimum_step_,
            }
        )

        iter_counter += 1

    save_pickle(Path(tune_res["output_dir"]) / "results.pkl", results)


if __name__ == "__main__":
    main()
