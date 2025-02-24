from __future__ import print_function


import numpy as np
np.random.seed(1234)  # for reproducibility?

import os
os.environ["THEANO_FLAGS"] = "cuda.root=/usr/local/cuda,device=gpu,floatX=float32"

import warnings

with warnings.catch_warnings():
    warnings.filterwarnings("ignore",category=DeprecationWarning)
    import lasagne
    from lasagne import layers
    from lasagne.updates import nesterov_momentum
    
import theano
import theano.tensor as T
import theano.tensor as T
from theano import function, config, shared, sandbox
import lasagne

# specifying the gpu to use
import theano.sandbox.cuda
theano.sandbox.cuda.use('gpu1')

# from http://blog.christianperone.com/2015/08/convolutional-neural-networks-and-feature-extraction-with-python/
import matplotlib
import matplotlib.pyplot as plt
import matplotlib.cm as cm
import cPickle as pickle
from urllib import urlretrieve
import cPickle as pickle
import os
import gzip
import numpy as np
import theano


from nolearn.lasagne import NeuralNet
from nolearn.lasagne import visualize
from sklearn.metrics import classification_report
from sklearn.metrics import confusion_matrix

import logging
from pylearn2.datasets import cache, dense_design_matrix
from pylearn2.expr.preprocessing import global_contrast_normalize
from pylearn2.utils import contains_nan
from pylearn2.utils import serial
from pylearn2.utils import string_utils

_logger = logging.getLogger(__name__)



# User - created files
import train_lipreadingTCDTIMIT # load training functions
from datasetClass import CIFAR10 # load the binary dataset in proper format
# from loadData import CIFAR10   # load the binary dataset in proper format
from buildNetworks import *

def main ():
    # BN parameters
    batch_size = 32
    print("batch_size = " + str(batch_size))
    # alpha is the exponential moving average factor
    alpha = .1
    print("alpha = " + str(alpha))
    epsilon = 1e-4
    print("epsilon = " + str(epsilon))

    # activation
    activation = T.nnet.relu
    print("activation = T.nnet.relu")

    # Training parameters
    num_epochs = 40
    print("num_epochs = " + str(num_epochs))

    # Decaying LR
    LR_start = 0.002
    print("LR_start = " + str(LR_start))
    LR_fin = 0.0000003
    print("LR_fin = " + str(LR_fin))
    LR_decay = (LR_fin / LR_start) ** (1. / num_epochs)
    print("LR_decay = " + str(LR_decay))
    # BTW, LR decay might good for the BN moving average...

    shuffle_parts = 1
    print("shuffle_parts = " + str(shuffle_parts))

    print('Loading TCDTIMIT dataset...')
    database_binary_location = os.path.join(os.path.expanduser('~/TCDTIMIT/database_binary'))
    train_set, valid_set, test_set = load_dataset(database_binary_location, 0.85,0.1,0.05) #location, %train, %valid, %test

    print("the number of training examples is: ", len(train_set.X))
    print("the number of valid examples is: ", len(valid_set.X))
    print("the number of test examples is: ", len(test_set.X))

    print('Building the CNN...')

    # Prepare Theano variables for inputs and targets
    input = T.tensor4('inputs')
    target = T.matrix('targets')
    LR = T.scalar('LR', dtype=theano.config.floatX)

    # get the network structure
    cnn = build_network_google(activation, alpha, epsilon, input)
    #cnn = build_network_cifar10(activation, alpha, epsilon, input)

    ## resnet50; replace cnn by cnn['prob'] everywhere
    #cnn = build_network_resnet50(input)
    
    
    # load params from earlier training:
    with np.load('./results/allLipspeakers/allLipspeakers.npz') as f:
        param_values = [f['arr_%d' % i] for i in range(len(f.files))]
    lasagne.layers.set_all_param_values(cnn, param_values)

    # get output layer, for calculating loss etc
    train_output = lasagne.layers.get_output(cnn, deterministic=False)

    # squared hinge loss
    loss = T.mean(T.sqr(T.maximum(0., 1. - target * train_output)))

    # set all params to trainable
    params = lasagne.layers.get_all_params(cnn, trainable=True)
    updates = lasagne.updates.adam(loss_or_grads=loss, params=params, learning_rate=LR)

    test_output = lasagne.layers.get_output(cnn, deterministic=True)

    test_loss = T.mean(T.sqr(T.maximum(0., 1. - target * test_output)))
    test_err = T.mean(T.neq(T.argmax(test_output, axis=1), T.argmax(target, axis=1)), dtype=theano.config.floatX)

    # Compile a function performing a training step on a mini-batch (by giving the updates dictionary)
    # and returning the corresponding training loss:
    train_fn = theano.function([input, target, LR], loss, updates=updates)

    # Compile a second function computing the validation loss and accuracy:
    val_fn = theano.function([input, target], [test_loss, test_err])

    print('Training...')

    train_lipreadingTCDTIMIT.train(
            train_fn, val_fn,
            cnn,
            batch_size,
            LR_start, LR_decay,
            num_epochs,
            train_set.X, train_set.y,
            valid_set.X, valid_set.y,
            test_set.X, test_set.y,
            save_path="./TCDTIMITBestModel",
            shuffle_parts=shuffle_parts)


def unpickle(file):
    import cPickle
    fo = open(file, 'rb')
    dict = cPickle.load(fo)
    fo.close()
    return dict


def load_dataset (datapath = os.path.join(os.path.expanduser('~/TCDTIMIT/database_binary')), trainFraction=0.8, validFraction=0.1, testFraction=0.1):
    # from https://www.cs.toronto.edu/~kriz/cifar.html
    # also see http://stackoverflow.com/questions/35032675/how-to-create-dataset-similar-to-cifar-10

    # Lipspeaker 1:                  14627 phonemes,    14617 extacted and useable
    # Lipspeaker 2:  28363 - 14627 = 13736 phonemes     13707 extracted
    # Lipspeaker 3:  42535 - 28363 = 14172 phonemes     14153 extracted
    # total Lipspeakers:  14500 + 13000 + 14000 = 42477

    dtype = 'uint8'
    ntotal = 100000  # estimate, for initialization. takes some safty margin
    img_shape = (1, 120, 120)
    img_size = np.prod(img_shape)

    ### Load train and validation data ###
    # prepare data to load, only train on lipspkrs
    fnamesLipspkrs = ['Lipspkr%i.pkl' % i for i in range(1,4)]  # all 3 lipsteakers
    #fnamesVolunteers = ['Volunteer%i.pkl' % i for i in range(1,11)]  # 10 first volunteers
    fnames = fnamesLipspkrs #fnamesVolunteers
    datasets = {}
    for name in fnames:
        fname = os.path.join(datapath, name)
        if not os.path.exists(fname):
            raise IOError(fname + " was not found.")
        datasets[name] = cache.datasetCache.cache_file(fname)

    # load the images
    # first initialize the matrices
    lenx = ntotal
    xtrain = np.zeros((lenx, img_size), dtype=dtype)
    xvalid = np.zeros((lenx, img_size), dtype=dtype)

    ytrain = np.zeros((lenx, 1), dtype=dtype)
    yvalid = np.zeros((lenx, 1), dtype=dtype)

    # memory issues: print size
    memTot = xtrain.nbytes + xvalid.nbytes  + ytrain.nbytes + yvalid.nbytes
    # print("Empty matrices, memory required: ", memTot / 1000000, " MB")

    # now load train data
    trainLoaded = 0
    validLoaded = 0

    for i, fname in enumerate(fnames):
        print("Total loaded till now: ", trainLoaded + validLoaded, " out of ", ntotal)
        print("nbTrainLoaded: ", trainLoaded)
        print("nbValidLoaded: ", validLoaded)

        print('loading file %s' % datasets[fname])
        data = unpickle(datasets[fname])

        thisN = data['data'].shape[0]
        print("This dataset contains ", thisN, " images")

        thisTrain = int(trainFraction * thisN)
        thisValid = int(validFraction * thisN)
        print("now loading : nbTrain, nbValid")
        print("              ", thisTrain, thisValid)

        xtrain[trainLoaded:trainLoaded + thisTrain, :] = data['data'][0:thisTrain]
        xvalid[validLoaded:validLoaded + thisValid, :] = data['data'][thisTrain:thisTrain + thisValid]

        ytrain[trainLoaded:trainLoaded + thisTrain, 0] = data['labels'][0:thisTrain]
        yvalid[validLoaded:validLoaded + thisValid, 0] = data['labels'][thisTrain:thisTrain + thisValid]

        trainLoaded += thisTrain
        validLoaded += thisValid

        if (trainLoaded + validLoaded) >= ntotal:
            print("loaded too many?")
            break

    nvalid = validLoaded
    ntrain = trainLoaded
    print("Total loaded till now: ", trainLoaded + validLoaded, " out of ", ntotal)
    print("nbTrainLoaded: ", trainLoaded)
    print("nbValidLoaded: ", validLoaded)
    
    
    
    ###  Now, load the test data  ###

    # prepare data to load
    #fnamesLipspkrs = ['Lipspkr%i.pkl' % i for i in range(1, 4)]  # all 3 lipsteakers
    fnamesVolunteers = ['Volunteer%i.pkl' % i for i in range(1, 11)]  # 12 first volunteers
    fnames = fnamesVolunteers

    # remove 10 worst speakers: 2, 57, 47, 42, 54, 46, 29, 52, 34, 45
    
    datasets = {}
    for name in fnames:
        fname = os.path.join(datapath, name)
        if not os.path.exists(fname):
            raise IOError(fname + " was not found.")
        datasets[name] = cache.datasetCache.cache_file(fname)

    # load the images
    # first initialize the matrices
    lenxtest = ntotal * testFraction
    xtest = np.zeros((lenxtest, img_size), dtype=dtype)
    ytest = np.zeros((lenxtest, 1), dtype=dtype)

    # now load train data
    testLoaded = 0

    for i, fname in enumerate(fnames):
        print("nbTestLoaded: ", testLoaded)
    
        print('loading file %s' % datasets[fname])
        data = unpickle(datasets[fname])
    
        thisN = data['data'].shape[0]
        print("This dataset contains ", thisN, " images")
    
        thisTrain = int(trainFraction * thisN)
        thisValid = int(validFraction * thisN)
        thisTest = thisN - thisTrain - thisValid  # compensates for rounding
        print("now loading : nbTrain, nbValid, nbTest")
        print("              ", thisTrain, thisValid, thisTest)
    
        xtest[testLoaded:testLoaded + thisTest, :] = data['data'][thisTrain + thisValid:thisN]
        ytest[testLoaded:testLoaded + thisTest, 0] = data['labels'][thisTrain + thisValid:thisN]
    
        testLoaded += thisTest
    
        if (testLoaded) >= lenxtest:
            print("loaded too many?")
            break

    ntest = testLoaded
    print("nbTestLoaded: ", testLoaded)




    # remove unneeded rows
    xtrain = xtrain[0:trainLoaded]
    xvalid = xvalid[0:validLoaded]
    xtest = xtest[0:testLoaded]
    ytrain = ytrain[0:trainLoaded]
    yvalid = yvalid[0:validLoaded]
    ytest = ytest[0:testLoaded]

    memTot = xtrain.nbytes + xvalid.nbytes + xtest.nbytes + ytrain.nbytes + yvalid.nbytes + ytest.nbytes
    # print("Total memory size required: ", memTot / 1000000, " MB")

    # process this data, remove all zero rows (http://stackoverflow.com/questions/18397805/how-do-i-delete-a-row-in-a-np-array-which-contains-a-zero)
    # cast to numpy array
    if isinstance(ytrain, list):
        ytrain = np.asarray(ytrain).astype(dtype)
    if isinstance(yvalid, list):
        yvalid = np.asarray(yvalid).astype(dtype)
    if isinstance(ytest, list):
        ytest = np.asarray(ytest).astype(dtype)

    # fix labels (labels start at 1, but the library expects them to start at 0)
    ytrain = ytrain - 1
    yvalid = yvalid - 1
    ytest = ytest - 1

    # now, make objects with these matrices
    train_set = CIFAR10(xtrain, ytrain, img_shape)
    valid_set = CIFAR10(xvalid, yvalid, img_shape)
    test_set = CIFAR10(xtest, ytest, img_shape)

    # Inputs in the range [-1,+1]
    # def f1 (x):
    #     f = function([], sandbox.cuda.basic_ops.gpu_from_host(x * 2.0 / 255 - 1))
    #     return f()
    #
    # def scaleOnGpu (matrix):
    #     nbRows = matrix.shape[0]
    #     done = 0
    #     batchLength = 100
    #     thisBatchLength = batchLength
    #     i = 0
    #     while done != 1:
    #         if i + thisBatchLength > nbRows:
    #             done = 1
    #             thisBatchLength = nbRows - i
    #         # do the scaling on GPU
    #         matrix[i:(i + thisBatchLength), :] = f1(
    #                 shared(matrix[i:(i + thisBatchLength), :]))
    #         i += batchLength
    #     return matrix
    #
    # train_set.X = scaleOnGpu(train_set.X )
    # valid_set.X = scaleOnGpu(valid_set.X )
    # test_set.X = scaleOnGpu(test_set.X)

    train_set.X = np.subtract(np.multiply(2. / 255., train_set.X), 1.)
    valid_set.X = np.subtract(np.multiply(2. / 255., valid_set.X), 1.)
    test_set.X = np.subtract(np.multiply(2. / 255., test_set.X), 1.)

    train_set.X = np.reshape(train_set.X, (-1, 1, 120, 120))
    valid_set.X = np.reshape(valid_set.X, (-1, 1, 120, 120))
    test_set.X = np.reshape(test_set.X, (-1, 1, 120, 120))

    # flatten targets
    train_set.y = np.hstack(train_set.y)
    valid_set.y = np.hstack(valid_set.y)
    test_set.y = np.hstack(test_set.y)
    # Onehot the targets
    train_set.y = np.float32(np.eye(39)[train_set.y])
    valid_set.y = np.float32(np.eye(39)[valid_set.y])
    test_set.y = np.float32(np.eye(39)[test_set.y])
    # for hinge loss
    train_set.y = 2 * train_set.y - 1.
    valid_set.y = 2 * valid_set.y - 1.
    test_set.y = 2 * test_set.y - 1.

    return train_set, valid_set, test_set

# build_network_resnet is in the
def load_dataset_old (train_set_size):

    # from https://www.cs.toronto.edu/~kriz/cifar.html
    # also see http://stackoverflow.com/questions/35032675/how-to-create-dataset-similar-to-cifar-10

    # CIFAR10 files stored in /home/matthijs/Documents/Pylearn_datasets/cifar10/cifar-10-batches-py
    # then processed with /home/matthijs/bin/pylearn2/pylearn2/datasets/cifar10.py

    # our files are stored in /home/matthijs/TCDTIMIT/database_binary
    # and processed with ./loadData.py

    # Lipspeaker 1:                  14627 phonemes, apparently only 14530 extracted
    # Lipspeaker 2:  28363 - 14627 = 13736 phonemes
    # Lipspeaker 3:  42535 - 28363 = 14172 phonemes

    # lipspeaker 1 : 14627 -> 11.5k train, 1.5k valid, 1.627k test
    train_set = CIFAR10(which_set="train", start=0, stop=train_set_size)
    valid_set = CIFAR10(which_set="train", start=train_set_size, stop=13000)
    test_set = CIFAR10(which_set="test")


    # bc01 format
    # Inputs in the range [-1,+1]
    # print("Inputs in the range [-1,+1]")
    train_set.X = np.reshape(np.subtract(np.multiply(2. / 255., train_set.X), 1.), (-1, 1, 120, 120))
    valid_set.X = np.reshape(np.subtract(np.multiply(2. / 255., valid_set.X), 1.), (-1, 1, 120, 120))
    test_set.X = np.reshape(np.subtract(np.multiply(2. / 255., test_set.X), 1.), (-1, 1, 120, 120))
    # flatten targets
    train_set.y = np.hstack(train_set.y)
    valid_set.y = np.hstack(valid_set.y)
    test_set.y = np.hstack(test_set.y)
    # Onehot the targets
    train_set.y = np.float32(np.eye(39)[train_set.y])
    valid_set.y = np.float32(np.eye(39)[valid_set.y])
    test_set.y = np.float32(np.eye(39)[test_set.y])
    # for hinge loss
    train_set.y = 2 * train_set.y - 1.
    valid_set.y = 2 * valid_set.y - 1.
    test_set.y = 2 * test_set.y - 1.

    return train_set, valid_set, test_set



if __name__ == "__main__":
    main()
