import pandas as pd


class EnergyBalance:

    def __init__(self,pv,load):

        self.pv=pv

        self.load=load

    def compute(self):

        df=pd.DataFrame(index=self.pv.index)

        df["PV"]=self.pv

        df["Load"]=self.load

        df["SelfConsumption"]=df[["PV","Load"]].min(axis=1)

        df["GridImport"]=(df["Load"]-df["PV"]).clip(lower=0)

        df["CommunityExport"]=(df["PV"]-df["Load"]).clip(lower=0)

        return df