import transformers
from datasets import load_dataset
from transformers import AutoTokenizer, Trainer, TrainingArguments, AutoModelForSequenceClassification, AdamW, get_scheduler, DataCollatorWithPadding
from torch.utils.data import DataLoader
from tqdm.auto import tqdm
from accelerate import Accelerator
from datasets import load_metric
import torch
from sklearn.metrics import confusion_matrix
import numpy as np
import seaborn as sns
import matplotlib.pyplot as plt

nc = 2
accelerator = Accelerator()

data_dir = "./data/CrisisNLP_labeled_data_crowdflower/type_balanced"
dataset = load_dataset('csv', data_files={'train':data_dir+"/train.csv", 'test':data_dir+"/test.csv"})

tokenizer = AutoTokenizer.from_pretrained('roberta-base')

names = ["injured_or_dead_people", "donation_needs_or_offers_or_volunteering_services", "sympathy_and_emotional_support", "other_useful_information", "not_related_or_irrelevant", "infrastructure_and_utilities_damage", "caution_and_advice", "missing_trapped_or_found_people", "displaced_people_and_evacuations"]
def transform_labels(label):
    label = label["label"]
    num = -1
    # if label == "injured_or_dead_people":
    #     num = 0
    # elif label == "donation_needs_or_offers_or_volunteering_services":
    #     num = 1
    # elif label == "sympathy_and_emotional_support":
    #     num = 2
    # elif label == "other_useful_information":
    #     num = 3
    # elif label == "not_related_or_irrelevant":
    #     num = 4
    # elif label == "infrastructure_and_utilities_damage":
    #     num = 5
    # elif label == "caution_and_advice":
    #     num = 6
    # elif label == "missing_trapped_or_found_people":
    #     num = 7
    # elif label == "displaced_people_and_evacuations":
    #     num = 8
    if label == "injured_or_dead_people":
        num=0
    else:
        num=1

    return {"labels":num}

def tokenize_data(example):
    return tokenizer(example["tweet_text"], padding='max_length')


dataset = dataset.map(tokenize_data, batched=True)

dataset = dataset.map(transform_labels, remove_columns=["tweet_id", "tweet_text", "label"])

data_collator = DataCollatorWithPadding(tokenizer=tokenizer)

train_loader = DataLoader(dataset["train"], shuffle=True, batch_size=8, collate_fn=data_collator)
test_loader = DataLoader(dataset["test"], batch_size=8, collate_fn=data_collator)

model = AutoModelForSequenceClassification.from_pretrained("roberta-base", num_labels=nc)
optimizer = AdamW(model.parameters(), lr=3e-5)

train_loader, test_loader, model, optimizer = accelerator.prepare(train_loader, test_loader, model, optimizer)

num_epochs = 4
num_training_steps = num_epochs * len(train_loader)
lr_scheduler = get_scheduler(
    "linear",
    optimizer=optimizer,
    num_warmup_steps=0,
    num_training_steps=num_training_steps,
)

progress_bar = tqdm(range(num_training_steps))

model.train()
for epoch in range(num_epochs):
    for batch in train_loader:
        outputs = model(**batch)
        loss = outputs.loss
        accelerator.backward(loss)

        optimizer.step()
        lr_scheduler.step()
        optimizer.zero_grad()
        progress_bar.update(1)

metric1 = load_metric("accuracy")
metric2 = load_metric("f1")

model.eval()

preds = []
labels = []
for batch in test_loader:
    with torch.no_grad():
        outputs = model(**batch)
    
    logits = outputs.logits
    predictions = torch.argmax(logits, dim=-1)
    preds.append(predictions)
    labels.append(batch["labels"])
    metric1.add_batch(predictions=predictions, references=batch["labels"])
    metric2.add_batch(predictions=predictions, references=batch["labels"])


print(metric1.compute())
print(metric2.compute(average="macro"))

preds = torch.cat(preds).cpu()
labels = torch.cat(labels).cpu()
print(str(labels.shape) + "***************")


cm = confusion_matrix(y_true = labels, y_pred=preds )
ax = plt.subplot()
sns.heatmap(cm, annot=True, fmt="g", ax=ax, cmap="Greens")
ax.set_xlabel('Predicted Labels')
ax.set_ylabel('True Labels')
ax.set_title('Confusion matrix')
ax.xaxis.set_ticklabels(range(nc))
ax.yaxis.set_ticklabels(range(nc))
plt.show()

fig = ax.get_figure()

fig.savefig('./figures/type-balanced-4.jpg')

rowsum = np.sum(cm, axis=0)
colsum = np.sum(cm, axis=1)
tp = cm[0][0]
fp = rowsum[0] - tp
fn = colsum[0] - tp
tn = np.sum(cm) - (fp+fn+tp)

print("True Positive", tp)
print("True Negative", tn)
print("False Positive", fp)
print("False Negative", fn)

print("False Positive Rate", fp/(fp+tn))

accelerator.unwrap_model(model).save_pretrained("./models/type_balanced")
