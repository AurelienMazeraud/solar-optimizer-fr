import numpy as np
import pandas as pd


class Loan:
    """Pret a annuites constantes (amortissement classique)."""

    def __init__(self, principal, annual_rate, duration_years):
        self.principal = principal
        self.annual_rate = annual_rate
        self.duration_years = duration_years

    def annual_payment(self):

        if self.principal <= 0 or self.duration_years <= 0:
            return 0.0

        r = self.annual_rate
        n = self.duration_years

        if r == 0:
            return self.principal / n

        return self.principal * r / (1 - (1 + r) ** (-n))

    def schedule(self, total_years):

        payment = self.annual_payment()

        payments = np.zeros(total_years)

        n = min(self.duration_years, total_years)

        payments[:n] = payment

        return payments


class Investment:
    """
    Modele economique d'une installation photovoltaique.

    Prend en compte le cout d'investissement, les aides/subventions, un
    financement optionnel (apport + pret), les tarifs de valorisation de
    l'energie (autoconsommation vs revente, dont le tarif de revente
    depend de la configuration retenue), l'inflation du prix de
    l'electricite et la degradation des panneaux dans le temps, pour
    projeter le cashflow annuel, le temps de retour sur investissement et
    la valeur actuelle nette (VAN).

    Le TURPE reduit (autoconsommation collective) et d'eventuels frais de
    gestion PMO (Personne Morale Organisatrice) peuvent etre deduits du
    prix de revente via turpe_reduced_eur_per_kwh et pmo_fee_ratio — ils
    ne s'appliquent qu'a l'energie exportee/valorisee collectivement, pas
    a l'autoconsommation individuelle (qui ne transite pas par le reseau
    public). Valeurs par defaut a 0 (non pris en compte) : a renseigner
    selon le montage reel de l'operation, ces parametres reglementaires
    et contractuels variant sensiblement d'un cas a l'autre.
    """

    # Tarifs de revente usuels a titre indicatif (a verifier / ajuster
    # selon le contrat reel : ces tarifs reglementes evoluent regulierement).
    # "Obligation d'achat" mis a jour suite a l'arrete modificatif du
    # 1er juin 2026 (JO du 4 juin 2026) : suppression de la prime a
    # l'autoconsommation et chute du tarif de rachat du surplus a environ
    # 0,011 EUR/kWh pour les installations <= 9 kWc (indexe +2%/an sur 20
    # ans). Les installations raccordees avant cette date conservent
    # l'ancien tarif pour la duree de leur contrat.
    EXPORT_PRESETS = {
        "Obligation d'achat (surplus, tarif reglemente, depuis 06/2026)": 0.011,
        "Autoconsommation collective (tarif libre negocie)": 0.13,
        "Vente totale (tarif reglemente)": 0.1276,
        "Personnalise": None,
    }

    def __init__(
        self,
        capex,
        subsidies=0.0,
        down_payment=0.0,
        loan_rate=0.0,
        loan_duration_years=0,
        price_self_consumption=0.2305,
        price_export=0.10,
        price_inflation=0.02,
        panel_degradation=0.005,
        duration_years=25,
        discount_rate=0.03,
        turpe_reduced_eur_per_kwh=0.0,
        pmo_fee_ratio=0.0,
    ):
        self.capex = capex
        self.subsidies = subsidies
        self.down_payment = down_payment
        self.loan_rate = loan_rate
        self.loan_duration_years = loan_duration_years
        self.price_self_consumption = price_self_consumption
        self.price_export = price_export
        self.price_inflation = price_inflation
        self.panel_degradation = panel_degradation
        self.duration_years = duration_years
        self.discount_rate = discount_rate
        self.turpe_reduced_eur_per_kwh = turpe_reduced_eur_per_kwh
        self.pmo_fee_ratio = pmo_fee_ratio

        self.net_cost = max(capex - subsidies, 0.0)
        self.loan_principal = max(self.net_cost - down_payment, 0.0)

        self.loan = None
        if self.loan_principal > 0 and loan_duration_years > 0:
            self.loan = Loan(self.loan_principal, loan_rate, loan_duration_years)

        # decaisse initialement : l'apport si pret, sinon le cout net complet
        self.initial_outlay = self.down_payment if self.loan else self.net_cost

        # Prix net de revente effectivement percu par le producteur, une
        # fois deduits le TURPE reduit ACC et les frais de gestion PMO
        # (uniquement sur le flux exporte/valorise collectivement).
        self.effective_export_price = max(
            self.price_export * (1 - self.pmo_fee_ratio) - self.turpe_reduced_eur_per_kwh,
            0.0,
        )

    def cashflow(self, self_consumption_kwh_year1, export_kwh_year1):
        """
        Construit le cashflow annuel (annee 1 a duration_years).

        self_consumption_kwh_year1 / export_kwh_year1 : valeurs de la
        premiere annee (issues d'EnergyBalance), extrapolees ensuite avec
        la degradation des panneaux et l'inflation du prix de l'electricite.
        """

        years = np.arange(1, self.duration_years + 1)

        degradation = (1 - self.panel_degradation) ** (years - 1)
        inflation = (1 + self.price_inflation) ** (years - 1)

        savings = self_consumption_kwh_year1 * degradation * self.price_self_consumption * inflation
        sales = export_kwh_year1 * degradation * self.effective_export_price * inflation

        gross_benefit = savings + sales

        loan_payments = self.loan.schedule(self.duration_years) if self.loan else np.zeros(self.duration_years)

        net_cashflow = gross_benefit - loan_payments

        df = pd.DataFrame({
            "Year": years,
            "Savings": savings,
            "Sales": sales,
            "GrossBenefit": gross_benefit,
            "LoanPayment": loan_payments,
            "NetCashflow": net_cashflow,
        })

        df["CumulativeNet"] = df["NetCashflow"].cumsum() - self.initial_outlay

        return df

    def payback_period(self, cashflow_df):
        """Temps de retour sur investissement, en annees (interpolation lineaire).

        Retourne None si l'investissement n'est pas rentabilise sur la
        duree simulee.
        """

        prev_year = 0
        prev_cum = -self.initial_outlay

        for _, row in cashflow_df.iterrows():

            year = row["Year"]
            cum = row["CumulativeNet"]

            if cum >= 0:
                if cum == prev_cum:
                    return year
                fraction = (0 - prev_cum) / (cum - prev_cum)
                return prev_year + fraction

            prev_year = year
            prev_cum = cum

        return None

    def npv(self, cashflow_df):
        """Valeur actuelle nette (VAN) au taux d'actualisation choisi."""

        years = cashflow_df["Year"].values
        net = cashflow_df["NetCashflow"].values

        discounted = net / (1 + self.discount_rate) ** years

        return discounted.sum() - self.initial_outlay
