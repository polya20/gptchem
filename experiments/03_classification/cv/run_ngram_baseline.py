import os
import time
from pathlib import Path

import numpy as np
import pandas as pd
from fastcore.xtras import save_pickle
from sklearn.feature_extraction.text import CountVectorizer
from sklearn.model_selection import train_test_split
from sklearn.naive_bayes import MultinomialNB

from gptchem.data import get_moosavi_cv_data
from gptchem.evaluator import evaluate_classification

train_sizes = [10, 20, 50, 100]
num_classes = [2, 5]
test_size = 100
representations = ["grouped_mof", "mofid"]

num_repeats = 10
outdir = "ngram_baseline"

if not os.path.exists(outdir):
    os.makedirs(outdir)


def train_test_model(num_classes, representation, num_train_points, seed):
    data = get_moosavi_cv_data()
    data = data.dropna(subset=["Cv_gravimetric_300.00"])
    data["binned"] = pd.qcut(
        data["Cv_gravimetric_300.00"], num_classes, labels=np.arange(num_classes)
    )
    train, test = train_test_split(
        data,
        train_size=num_train_points,
        test_size=min(test_size, len(data) - num_train_points),
        random_state=seed,
        stratify=data["binned"],
    )

    vectorizer = CountVectorizer()
    X_train = vectorizer.fit_transform(train[representation])
    X_test = vectorizer.transform(test[representation])

    clf = MultinomialNB()
    clf.fit(X_train, train["binned"])

    y_pred = clf.predict(X_test)
    y_true = test["binned"]

    metrics = evaluate_classification(y_true, y_pred)

    print(f"Ran train size {num_train_points} and got accuracy {metrics['accuracy']:.3f}")

    summary = {
        **metrics,
        "train_size": num_train_points,
        "num_classes": num_classes,
        "representation": representation,
    }

    timestr = time.strftime("%Y%m%d-%H%M%S")

    save_pickle(
        Path(
            os.path.join(
                outdir, f"{timestr}_{seed}_{representation}_{num_classes}_{num_train_points}.pkl"
            )
        ),
        summary,
    )


if __name__ == "__main__":
    for num_class in num_classes:
        for representation in representations:
            for num_train_point in train_sizes:
                for seed in range(num_repeats):
                    train_test_model(num_class, representation, num_train_point, seed)
