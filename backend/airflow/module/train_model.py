import os

import pandas as pd
import torch
import transformers
from datasets import Dataset, concatenate_datasets
from dotenv import load_dotenv
from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
from transformers import (AutoModelForCausalLM, AutoTokenizer,
                          BitsAndBytesConfig)

load_dotenv()
huggingface_write_token = os.getenv("HUGGINGFACE_WRITE_TOKEN")

class Autodata:
    def __init__(self, data_path, max_length=1024, tokenizer=None):
        self.max_length = max_length
        self.tokenizer = tokenizer
        self.concat_dataset = self.concat_datasets(data_path)
        self.tokenizer_dataset = self.tokenizing_dataset(self.concat_dataset)

    def concat_datasets(self, data_path):
        datasets = []
        dataset = pd.read_csv(data_path)
        dataframe = dataset[["question", "answer"]]
        dataset = Dataset.from_pandas(dataframe)
        datasets.append(dataset)

        combined_dataset = concatenate_datasets(datasets)

        return combined_dataset

    def tokenizing_dataset(self, dataset):
        data = dataset.map(
            lambda x: {
                "text": f"아래는 작업을 설명하는 명령어입니다. 요청을 적절히 완료하는 응답을 작성하세요.\n\n### 명령어:\n{x['question']}\n\n### 응답:\n{x['answer']}<|endoftext|>"
            }
        )
        data = data.map(
            lambda samples: self.tokenizer(
                samples["text"],
                truncation=True,
                max_length=self.max_length,
                padding=False,
                return_tensors=None,
            ),
            batched=True,
        )

        return data.shuffle()

def load_model(model_name):
    # bnb_config = BitsAndBytesConfig(
    #     load_in_4bit=True,
    #     bnb_4bit_use_double_quant=True,
    #     bnb_4bit_quant_type="nf4",
    #     bnb_4bit_compute_dtype=torch.bfloat16,
    # )
    tokenizer = AutoTokenizer.from_pretrained(model_name)
    model = AutoModelForCausalLM.from_pretrained(
        model_name
    )
    model.gradient_checkpointing_enable()
    model = prepare_model_for_kbit_training(model)

    config = LoraConfig(
        r=8,
        lora_alpha=32,
        target_modules=["query_key_value"],
        lora_dropout=0.05,
        bias="none",
        task_type="CAUSAL_LM",
    )

    model = get_peft_model(model, config)
    print_trainable_parameters(model)

    return model, tokenizer


def print_trainable_parameters(model):
    """
    Prints the number of trainable parameters in the model.
    """
    trainable_params = 0
    all_param = 0
    for _, param in model.named_parameters():
        all_param += param.numel()
        if param.requires_grad:
            trainable_params += param.numel()
    print(
        f"trainable params: {trainable_params} || all params: {all_param} || trainable%: {100 * trainable_params / all_param}"
    )

def train_model():
    model_id = "nlpai-lab/kullm-polyglot-5.8b-v2"
    model, tokenizer = load_model(model_id)
    tokenizer.pad_token = tokenizer.eos_token
    BASE_DIR = os.path.join(os.path.dirname(os.path.abspath(os.path.dirname(__file__))), "data")
    TRAIN_DATA_PATH = os.path.join(BASE_DIR, "train_data.csv")
    EVAL_DATA_PATH = os.path.join(BASE_DIR, "eval_data.csv")
    train_data = Autodata(data_path=TRAIN_DATA_PATH, tokenizer=tokenizer).tokenizer_dataset
    val_data = Autodata(data_path=EVAL_DATA_PATH, tokenizer=tokenizer).tokenizer_dataset
    trainer = transformers.Trainer(
        model=model,
        train_dataset=train_data,
        eval_dataset=val_data,
        args=transformers.TrainingArguments(
            per_device_train_batch_size=16,
            gradient_accumulation_steps=1,
            num_train_epochs=6,
            learning_rate=1e-4,
            fp16=True,
            logging_steps=10,
            save_strategy="epoch",
            evaluation_strategy="epoch",
            output_dir="./model_outputs",
            optim="paged_adamw_8bit",
        ),
        data_collator=transformers.DataCollatorForLanguageModeling(
            tokenizer, mlm=False
        ),
    )
    model.config.use_cache = (
        False  # silence the warnings. Please re-enable for inference!
    )
    trainer.train()

    push_model_id = "YoonSeul/LawBot-airflow-test"  

    model.push_to_hub(
        push_model_id, use_temp_dir=True, use_auth_token=huggingface_write_token
    )
    print(f"{push_model_id} 모델 업로드 완료!")


if __name__ == "__main__":
    train_model()
