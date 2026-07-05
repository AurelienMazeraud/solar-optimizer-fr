class Economics:

    def __init__(self,balance):

        self.balance=balance

    def yearly(

        self,

        hp=0.2305,

        community=0.13

    ):

        savings=self.balance["SelfConsumption"].sum()*hp

        sales=self.balance["CommunityExport"].sum()*community

        purchase=self.balance["GridImport"].sum()*hp

        return {

            "Savings":savings,

            "Sales":sales,

            "Purchase":purchase,

            "NetBenefit":savings+sales

        }