#from .evaluate import get_scores
import torch
import torch.optim as optim
#from model.net import *

import util
class Trainer():
    def __init__(self, model, lrate, wdecay, clip, step_size, seq_out_len, scaler, device, patience=50,
                 cl=True, mask=False):
        self.scaler = scaler
        self.model = model
        self.model.to(device)
        self.optimizer = optim.Adam(self.model.parameters(), lr=lrate, weight_decay=wdecay)
        self.scheduler = optim.lr_scheduler.CosineAnnealingLR(self.optimizer, T_max=int(patience * 0.8))
        self.loss = util.masked_mae
        self.clip = clip
        self.step = step_size
        self.iter = 1
        self.task_level = 1
        self.seq_out_len = seq_out_len
        self.cl = cl
        self.mask = mask
        self.cl_done = not self.cl
    def train(self, input, real, pred_time):
        self.model.train()
        self.optimizer.zero_grad()
        output = self.model(input, real=real, pred_time=pred_time, batch_seen=self.iter)
        # output = output.transpose(1,3)
        predict = self.scaler.inverse_transform(output)
        real = self.scaler.inverse_transform(real)
        assert predict.shape == real.shape, f'{predict.shape}, {real.shape}'
        if self.cl and self.iter % self.step == 0:
            if self.task_level <= self.seq_out_len:
                self.task_level += 1
                print('task_level:', self.task_level)
                self.cl_done = (self.task_level > self.seq_out_len)
        if self.cl:
            if self.mask:           
                loss = self.loss(predict[:, :self.task_level, :, :], real[:, :self.task_level, :, :], 0.0)
            else:
                 loss = self.loss(predict[:, :self.task_level, :, :], real[:, :self.task_level, :, :])
        else:
            if self.mask:
                loss = self.loss(predict, real, 0.0)
            else:
                loss = self.loss(predict, real)

        loss.backward()

        if self.clip is not None:
            torch.nn.utils.clip_grad_norm_(self.model.parameters(), self.clip)

        self.optimizer.step()
    
        self.iter += 1
        return loss.item()

    def eval(self, input, real, pred_time):
        self.model.eval()
        output = self.model(input, pred_time=pred_time)
        # output = output.transpose(1,3)
        #real = torch.unsqueeze(real_val,dim=1)
        predict = self.scaler.inverse_transform(output)
        real = self.scaler.inverse_transform(real)
        #scores =get_scores(predict, real, self.mask, 'multi')

        # mape = util.masked_mape(predict,real,0.0).item()
        if self.mask:
            loss = self.loss(predict, real, 0.0)           
        #     rmse = util.masked_rmse(predict,real,0.0).item()
        else:
            loss = self.loss(predict, real)
        #     rmse = util.masked_rmse(predict,real).item()
        # return loss.item()
        return loss.item(), predict, real


class Optim(object):

    def _makeOptimizer(self):
        if self.method == 'sgd':
            self.optimizer = optim.SGD(self.params, lr=self.lr, weight_decay=self.lr_decay)
        elif self.method == 'adagrad':
            self.optimizer = optim.Adagrad(self.params, lr=self.lr, weight_decay=self.lr_decay)
        elif self.method == 'adadelta':
            self.optimizer = optim.Adadelta(self.params, lr=self.lr, weight_decay=self.lr_decay)
        elif self.method == 'adam':
            self.optimizer = optim.Adam(self.params, lr=self.lr, weight_decay=self.lr_decay)
        else:
            raise RuntimeError("Invalid optim method: " + self.method)

    def __init__(self, params, method, lr, clip, lr_decay=1, start_decay_at=None):
        self.params = params  # careful: params may be a generator
        self.last_ppl = None
        self.lr = lr
        self.clip = clip
        self.method = method
        self.lr_decay = lr_decay
        self.start_decay_at = start_decay_at
        self.start_decay = False

        self._makeOptimizer()

    def step(self):
        # Compute gradients norm.
        grad_norm = 0
        if self.clip is not None:
            torch.nn.utils.clip_grad_norm_(self.params, self.clip)

        # for param in self.params:
        #     grad_norm += math.pow(param.grad.data.norm(), 2)
        #
        # grad_norm = math.sqrt(grad_norm)
        # if grad_norm > 0:
        #     shrinkage = self.max_grad_norm / grad_norm
        # else:
        #     shrinkage = 1.
        #
        # for param in self.params:
        #     if shrinkage < 1:
        #         param.grad.data.mul_(shrinkage)
        self.optimizer.step()
        return  grad_norm

    # decay learning rate if val perf does not improve or we hit the start_decay_at limit
    def updateLearningRate(self, ppl, epoch):
        if self.start_decay_at is not None and epoch >= self.start_decay_at:
            self.start_decay = True
        if self.last_ppl is not None and ppl > self.last_ppl:
            self.start_decay = True

        if self.start_decay:
            self.lr = self.lr * self.lr_decay
            print("Decaying learning rate to %g" % self.lr)
        #only decay for one epoch
        self.start_decay = False

        self.last_ppl = ppl

        self._makeOptimizer()
