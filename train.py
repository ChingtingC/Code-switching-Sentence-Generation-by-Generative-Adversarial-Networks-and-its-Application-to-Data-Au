#!/usr/bin/env python
# encoding: utf-8

import random
import codecs
import time
import os
import sklearn.preprocessing
import jieba.posseg as pseg
import numpy as np
from tqdm import tqdm
from argparse import ArgumentParser
from keras import backend as K
from keras.callbacks import TensorBoard, EarlyStopping
from keras.preprocessing.text import Tokenizer
from keras.preprocessing.sequence import pad_sequences
from utils import make_trainable, translate, translate_output, write_log, str2bool, get_action, evaluate_acc#, plot_loss
from build_model import GAN


# Add arguement
parser = ArgumentParser()
parser.add_argument("-l", dest = "MAX_SEQUENCE_LENGTH", type = int, default = 30)
parser.add_argument("-B", dest = "BATCH_SIZE",          type = int, default = 32)
parser.add_argument("-E", dest = "EPOCH_NUMBER",        type = int, default = 100)
parser.add_argument("-e", dest = "EMBEDDING_SIZE",      type = int, default = 150)
parser.add_argument("-p", dest = "EMBEDDING_POS",       type = int, default = -1) # No defining -> word only
parser.add_argument("-n", dest = "NOISE_SIZE",          type = int, default = 0)
parser.add_argument("-L", dest = "HIDDEN_SIZE_L",       type = int, default = 16)
parser.add_argument("-G", dest = "HIDDEN_SIZE_G",       type = int, default = 16)
parser.add_argument("-D", dest = "HIDDEN_SIZE_D",       type = int, default = 32)
parser.add_argument("-d", dest = "DROPOUT_RATE",      type = float, default = 0.1)
parser.add_argument("-t", dest = "GOPT",              type = float, default = 1e-3)
parser.add_argument("-T", dest = "DOPT",              type = float, default = 1e-2)
parser.add_argument("-m", dest = "MODEL_PATH",                      default = "model/")
parser.add_argument("-c", dest = "CORPUS_NAME",                     default = "sample")
args = parser.parse_args()

## Initial parameter setting
MAX_SEQUENCE_LENGTH = args.MAX_SEQUENCE_LENGTH
BATCH_SIZE = args.BATCH_SIZE
EPOCH_NUMBER = args.EPOCH_NUMBER
EMBEDDING_SIZE = args.EMBEDDING_SIZE
EMBEDDING_POS = args.EMBEDDING_POS
NOISE_SIZE = args.NOISE_SIZE
HIDDEN_SIZE_G = args.HIDDEN_SIZE_G
HIDDEN_SIZE_L = args.HIDDEN_SIZE_L
HIDDEN_SIZE_D = args.HIDDEN_SIZE_D
DROPOUT_RATE = args.DROPOUT_RATE
MODEL_PATH = args.MODEL_PATH
CORPUS_NAME = args.CORPUS_NAME
gopt = args.GOPT
dopt = args.DOPT


## Initial declaration
np.random.seed(0)
text_cs = []
text_zh = []
if not WORD_ONLY:
    pos_seq_cs = []
    pos_seq_zh = []

postag = dict()
word_index = dict()

# Set up loss storage vector
losses = {"d":[], "g":[]}
log_path = './logs/' + MODEL_PATH
callbacks = TensorBoard(log_path)

# Write log
log_g = 'train_loss_g'
log_d = 'train_loss_d'

if MODEL_PATH[-1] is not "/":
    MODEL_PATH = MODEL_PATH + "/"

try:
    os.stat(MODEL_PATH)
except:
    os.mkdir(MODEL_PATH)

try:
    os.stat(log_path)
except:
    os.mkdir(log_path)

if EMBEDDING_POS <= 0:
    WORD_ONLY = True
else:
    WORD_ONLY = False


print("========== LoadING various data")

## Define Pos tag dict
if not WORD_ONLY:
    with open("local/postag.txt", "r") as pos_dict:
        idx = 1
        for line in pos_dict:
            line = line.strip()
            postag[line] = idx
            idx = idx + 1

## Define word index dict
with open("local/dict.txt", "r") as word_dict:
    idx = 1
    for line in word_dict:
        line = line.strip()
        word_index[line] = idx
        idx = idx + 1

## Load code-switching text for training
with open("corpus/" + CORPUS_NAME + "/text/train.cs.txt", "r") as input_data:
    for line in input_data:
        text_cs.append(line.strip())

## Load chinese sentence for training
with open("corpus/" + CORPUS_NAME + "/text/train.mono.txt", "r") as input_data:
     for line in input_data:
         text_zh.append(line.strip())

## Load code-switching pos for training
if not WORD_ONLY:
    with open("corpus/" + CORPUS_NAME + "/pos/train.cs.txt", "r") as input_data:
        for line in input_data:
            line = line.strip().split(' ')
            pos_seq_cs.append(line)

## Load chinese POS for training
if not WORD_ONLY:
    with open("corpus/" + CORPUS_NAME + "/pos/train.mono.txt", "r") as input_data:
        for line in input_data:
            line = line.strip().split(' ')
            pos_seq_zh.append(line)

## Embed and zero pad data
tokenizer = Tokenizer(num_words = None, filters = '!"#$%&()*+,-./:;<=>?@[\\]^_`{|}~\t\n',
                      lower = False, split = " ", char_level = False)
tokenizer.word_index = word_index

sequences_cs = tokenizer.texts_to_sequences(text_cs)
sequences_zh = tokenizer.texts_to_sequences(text_zh)

emb_cs = np.asarray(pad_sequences(sequences_cs, maxlen = MAX_SEQUENCE_LENGTH, padding = 'post',
                    truncating = 'post', value = 0))
emb_zh = np.asarray(pad_sequences(sequences_zh, maxlen = MAX_SEQUENCE_LENGTH, padding = 'post',
                    truncating = 'post', value = 0))


## Set up our main training loop
def train_for_n(nb_epoch = 5000, BATCH_SIZE = 32):
    for e in tqdm(range(nb_epoch)):
        ### Shuffle and Batch the data
        _random  = np.random.randint(0, emb_cs.shape[0], size = BATCH_SIZE)
        _random2 = np.random.randint(0, emb_zh.shape[0], size = BATCH_SIZE)
        if not WORD_ONLY:
            pos_seq_cs_batch = pos_seq_cs[_random]
            pos_seq_zh_batch = pos_seq_zh[_random2]
        emb_cs_batch = emb_cs[_random]
        emb_zh_batch = emb_zh[_random2]
        noise_g = np.random.normal(0, 1, size = (BATCH_SIZE, MAX_SEQUENCE_LENGTH, NOISE_SIZE))
        reward_batch = np.zeros((BATCH_SIZE, 1))

        #############################################
        ### Train generator
        #############################################
        for ep in range(1):  # G v.s. D training ratio
            if not WORD_ONLY:
                output_g = generator.predict([emb_zh_batch, pos_seq_zh_batch, noise_g, reward_batch])
            else:
                output_g = generator.predict([emb_zh_batch, noise_g, reward_batch])
            action_g, action_one_hot_g = get_action(output_g)
            emb_g = translate(emb_zh_batch, action_g)
            text_g = translate_output(emb_zh_batch, action_g)

            # tag POS
            if not WORD_ONLY:
                pos_seq_g = []
                for line in text_g:
                    words = pseg.cut(line)
                    sub_data = []
                    idx = 0
                    for w in words:
                        if w.flag == "x":
                            idx = 0
                        elif idx == 0:
                            sub_data.append(postag[w.flag])
                            idx = 1
                    pos_seq_g.append(sub_data)

                pos_seq_g = pad_sequences(pos_seq_g, maxlen = MAX_SEQUENCE_LENGTH, padding='post',
                                          truncating = 'post', value = 0)

            one_hot_action = action_one_hot_g.reshape(BATCH_SIZE, MAX_SEQUENCE_LENGTH, 2)

            make_trainable(generator, True)

            if not WORD_ONLY:
                reward_batch = discriminator.predict([emb_g,pos_seq_g])[:,0]
                g_loss = generator.train_on_batch([emb_zh_batch, pos_seq_zh_batch, noise_g, reward_batch], one_hot_action)
            else:
                reward_batch = discriminator.predict([emb_g])[:,0]
                g_loss = generator.train_on_batch([emb_zh_batch, noise_g, reward_batch], one_hot_action)

            losses["g"].append(g_loss)
            write_log(callbacks, log_g, g_loss, len(losses["g"]))
            if g_loss < 0.15:  # early stop
                break
