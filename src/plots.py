import matplotlib.pyplot as plt


def monthly_energy(power):

    monthly = power.resample("ME").sum()

    plt.figure(figsize=(10, 5))

    monthly.plot(kind="bar")

    plt.ylabel("kWh")

    plt.title("Production mensuelle")

    plt.tight_layout()

    plt.show()
