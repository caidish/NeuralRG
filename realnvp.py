import torch
from torch.autograd import Variable
import numpy as np


class RealNVP(torch.nn.Module):

    def __init__(self, Nvars, Hs=10, Ht=10):
        """
        """
        super(RealNVP, self).__init__()
        self.Nvars = Nvars
        self.Nhalf = Nhalf

        self.s1 = torch.nn.Sequential(
                 torch.nn.Linear(Nhalf, Hs),
                 torch.nn.Sigmoid(),
                 torch.nn.Linear(Hs, Nhalf)
            )

        self.s2 = torch.nn.Sequential(
                 torch.nn.Linear(Nhalf, Hs),
                 torch.nn.Sigmoid(),
                 torch.nn.Linear(Hs, Nhalf)
            )

        self.t1 = torch.nn.Sequential(
                 torch.nn.Linear(Nhalf, Ht),
                 torch.nn.Sigmoid(),
                 torch.nn.Linear(Ht, Nhalf)
            )

        self.t2 = torch.nn.Sequential(
                 torch.nn.Linear(Nhalf, Ht),
                 torch.nn.Sigmoid(),
                 torch.nn.Linear(Ht, Nhalf)
            )

    def forward(self, x):
        """
        z = f(x)
        now only 2-layers 
        """
       
        y0 = x[:,0:self.Nhalf]
        y1 = x[:,self.Nhalf:self.Nvars] * torch.exp( self.s1(x[:, 0:self.Nhalf]))  \
                                                   + self.t1(x[:, 0:self.Nhalf])

        self.logjac = self.s1(x[:, 0:self.Nhalf]).sum(dim=1) 

        y0 = y0 * torch.exp(self.s2(y1)) +  self.t2(y1)
        #y1 = y1 nothing happens here 

        self.logjac += self.s2(y1).sum(dim=1)

        return torch.cat((y0, y1), 1)

    def logp(self, x):
        """
        logp(x) = logp(z) + sum_i s_i 
        """

        z = self.forward(x)
        return -0.5*(z**2).sum(dim=1) + self.logjac


if __name__=="__main__":
    import matplotlib.pyplot as plt 

    Nsamples = 1000
    Nvars = 2
    Nhalf = int(Nvars/2)

    model = RealNVP(Nvars)
    
    x = Variable(torch.randn(Nsamples, Nvars))
    z = model.forward(x)

    logp = model.logp(x)

    print(logp)

    x = x.data.numpy()
    z = z.data.numpy()

    plt.scatter(x[:,0], x[:,1], alpha=0.5, label='$x$')
    plt.scatter(z[:,0], z[:,1], alpha=0.5, label='$z$')

    plt.xlim([-5, 5])
    plt.ylim([-5, 5])

    plt.ylabel('$x_1$')
    plt.xlabel('$x_2$')
    plt.legend() 

    plt.show()