import torch
from torch import nn
import h5py
import numpy as np
import subprocess
import utils
from utils import HMCwithAccept
from .symmetry import Symmetrized

import flow
import source
import math

def symmetryMERAInit(L,d,nlayers,nmlp,nhidden,nrepeat,symmetryList,device,dtype,name = None):
    s = source.Gaussian([L]*d)

    depth = int(math.log(L,2))*nrepeat*2

    MaskList = []
    for _ in range(depth):
        masklist = []
        for n in range(nlayers):
            if n%2 == 0:
                b = torch.zeros(1,4)
                i = torch.randperm(b.numel()).narrow(0, 0, b.numel() // 2)
                b.zero_()[:,i] = 1
                b=b.view(1,2,2)
            else:
                b = 1-b
            masklist.append(b)
        masklist = torch.cat(masklist,0).to(torch.float32)
        MaskList.append(masklist)

    dimList = [4]
    for _ in range(nmlp):
        dimList.append(nhidden)
    dimList.append(4)

    layers = [flow.RNVP(MaskList[n], [utils.SimpleMLPreshape(dimList,[nn.ELU() for _ in range(nmlp)]+[None]) for _ in range(nlayers)], [utils.SimpleMLPreshape(dimList,[nn.ELU() for _ in range(nmlp)]+[utils.ScalableTanh(4)]) for _ in range(nlayers)]) for n in range(depth)]

    f = flow.MERA(2,L,layers,nrepeat,s)
    f = Symmetrized(f,symmetryList,name = name)
    f.to(device = device,dtype = dtype)
    return f

def learn(source, flow, batchSize, epochs, lr=1e-3, save = True, saveSteps = 10,savePath=None, weight_decay = 0.001, adaptivelr = True, measureFn = None):
    if savePath is None:
        savePath = "./opt/tmp/"
    params = list(flow.parameters())
    params = list(filter(lambda p: p.requires_grad, params))
    nparams = sum([np.prod(p.size()) for p in params])
    print ('total nubmer of trainable parameters:', nparams)
    optimizer = torch.optim.Adam(params, lr=lr, weight_decay=weight_decay)

    if adaptivelr:
        scheduler = torch.optim.lr_scheduler.StepLR(optimizer, step_size=500, gamma=0.7)

    LOSS = []
    ACC = []
    OBS = []


    for epoch in range(epochs):
        x,sampleLogProbability = flow.sample(batchSize)
        loss = sampleLogProbability.mean() - source.logProbability(x).mean()
        flow.zero_grad()
        loss.backward()
        optimizer.step()
        print("epoch:",epoch, "L:",loss.item())

        LOSS.append(loss.item())

        if save and epoch%saveSteps == 0:
            d = flow.save()
            torch.save(d,savePath+flow.name+".saving")

    return LOSS,ACC,OBS


def learnInterface(source, flow, batchSize, epochs, lr=1e-3, save = True, saveSteps = 10,savePath=None,keepSavings = 3, weight_decay = 0.001, adaptivelr = True, HMCsteps = 10, HMCthermal = 10, HMCepsilon = 0.2, measureFn = None):

    def cleanSaving(epoch):
        if epoch >= keepSavings*saveSteps:
            cmd =["rm","-rf",savePath+"savings/"+flow.name+"Saving_epoch"+str(epoch-keepSavings*saveSteps)+".saving"]
            subprocess.check_call(cmd)
            cmd =["rm","-rf",savePath+"records/"+flow.name+"Record_epoch"+str(epoch-keepSavings*saveSteps)+".hdf5"]
            subprocess.check_call(cmd)

    def latentU(z):
        x,_ = flow.inverse(z)
        return -(flow.prior.logProbability(z)+source.logProbability(x)-flow.logProbability(x))

    if savePath is None:
        savePath = "./opt/tmp/"
    params = list(flow.parameters())
    params = list(filter(lambda p: p.requires_grad, params))
    nparams = sum([np.prod(p.size()) for p in params])
    print ('total nubmer of trainable parameters:', nparams)
    optimizer = torch.optim.Adam(params, lr=lr, weight_decay=weight_decay)

    if adaptivelr:
        scheduler = torch.optim.lr_scheduler.StepLR(optimizer, step_size=500, gamma=0.7)

    LOSS = []
    ZACC = []
    XACC = []
    ZOBS = []
    XOBS = []

    z_ = flow.prior.sample(batchSize)
    x_ = flow.prior.sample(batchSize)

    for epoch in range(epochs):
        x,sampleLogProbability = flow.sample(batchSize)
        loss = sampleLogProbability.mean() - source.logProbability(x).mean()
        flow.zero_grad()
        loss.backward()
        optimizer.step()

        del sampleLogProbability
        del x

        print("epoch:",epoch, "L:",loss.item())

        LOSS.append(loss.item())

        if epoch%saveSteps == 0 or epoch == epochs:
            z_,zaccept = HMCwithAccept(latentU,z_.detach(),HMCthermal,HMCsteps,HMCepsilon)
            x_,xaccept = HMCwithAccept(source.energy,x_.detach(),HMCthermal,HMCsteps,HMCepsilon)
            with torch.no_grad():
                x_z,_ = flow.inverse(z_)
                z_last,_ = flow.forward(x_z)

            with torch.no_grad():
                Zobs = measureFn(x_z)
                Xobs = measureFn(x_)
            print("accratio_z:",zaccept.mean().item(),"obs_z:",Zobs.mean(),  ' +/- ' , Zobs.std()/np.sqrt(1.*batchSize))
            print("accratio_x:",xaccept.mean().item(),"obs_x:",Xobs.mean(),  ' +/- ' , Xobs.std()/np.sqrt(1.*batchSize))
            ZACC.append(zaccept.mean().cpu().item())
            XACC.append(xaccept.mean().cpu().item())
            ZOBS.append([Zobs.mean().item(),Zobs.std().item()/np.sqrt(1.*batchSize)])
            XOBS.append([Xobs.mean().item(),Xobs.std().item()/np.sqrt(1.*batchSize)])

            if save:
                with torch.no_grad():
                    samples,_ = flow.sample(batchSize)
                with h5py.File(savePath+"records/"+flow.name+"HMCresult_epoch"+str(epoch)+".hdf5","w") as f:
                    f.create_dataset("XZ",data=x_z.detach().cpu().numpy())
                    f.create_dataset("Y",data=x_.detach().cpu().numpy())
                    f.create_dataset("X",data=samples.detach().cpu().numpy())

                del x_z
                del samples

                with h5py.File(savePath+"records/"+flow.name+"Record_epoch"+str(epoch)+".hdf5", "w") as f:
                    f.create_dataset("LOSS",data=np.array(LOSS))
                    f.create_dataset("ZACC",data=np.array(ZACC))
                    f.create_dataset("ZOBS",data=np.array(ZOBS))
                    f.create_dataset("XACC",data=np.array(XACC))
                    f.create_dataset("XOBS",data=np.array(XOBS))
                d = flow.save()
                torch.save(d,savePath+"savings/"+flow.name+"Saving_epoch"+str(epoch)+".saving")
                cleanSaving(epoch)

    return LOSS,ZACC,ZOBS,XACC,XOBS
