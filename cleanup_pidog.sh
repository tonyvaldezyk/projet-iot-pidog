#!/bin/bash

# Script de nettoyage PiDog pour Raspberry Pi
# Résout les conflits GPIO et processus

echo "🧹 Nettoyage PiDog en cours..."

# 1. Arrêter tous les processus liés
echo "🛑 Arrêt des processus existants..."
sudo pkill -f pidog 2>/dev/null || true
sudo pkill -f robot_hat 2>/dev/null || true
sudo pkill -f flask 2>/dev/null || true
sudo pkill -f uvicorn 2>/dev/null || true

# 2. Nettoyer les GPIO
echo "🔌 Nettoyage des GPIO..."
sudo python3 -c "
try:
    import RPi.GPIO as GPIO
    GPIO.cleanup()
    print('✅ GPIO nettoyés')
except Exception as e:
    print(f'⚠️  Erreur GPIO: {e}')
" 2>/dev/null || true

# 3. Redémarrer pigpiod si installé
if systemctl is-active --quiet pigpiod; then
    echo "🔄 Redémarrage pigpiod..."
    sudo systemctl restart pigpiod
fi

# 4. Attendre la libération des ressources
echo "⏳ Attente libération des ressources..."
sleep 3

# 5. Vérifier les processus restants
echo "🔍 Vérification des processus restants..."
REMAINING=$(ps aux | grep -E "(pidog|robot_hat)" | grep -v grep | wc -l)
if [ $REMAINING -eq 0 ]; then
    echo "✅ Tous les processus sont arrêtés"
else
    echo "⚠️  $REMAINING processus encore actifs"
    ps aux | grep -E "(pidog|robot_hat)" | grep -v grep
fi

echo "🎉 Nettoyage terminé - Vous pouvez maintenant lancer l'API"