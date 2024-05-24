import os
import torch
from torch import optim
import torch.nn.functional as F
import lightning.pytorch as pl
from models.timae import TimeSeriesMaskedAutoencoder
from models.autoencoder.pl_model import LitAutoEncoder
from data.dataset import ShallowWaterDataset


class LitTiMAE(pl.LightningModule):
    def __init__(self):
        super().__init__()
        self.model = TimeSeriesMaskedAutoencoder(
            input_dim=3,
            latent_dim=512,
            hidden_dim=1024,
            encoder_num_heads=2,
            encoder_depth=6,
            decoder_num_heads=2,
            decoder_depth=2,
            forecast_steps=5
        )
        self.visulise_num = 5

        # load pretrained autoencoder
        state_dict = LitAutoEncoder.load_from_checkpoint('logs/autoencoder/lightning_logs/prod/checkpoints/epoch=49-step=14950.ckpt').model.state_dict()
        self.model.autoencoder.load_state_dict(state_dict)
        # freeze autoencoder
        for param in self.model.autoencoder.parameters():
            param.requires_grad = False

    def configure_optimizers(self):
        optimizer = optim.RAdam(
            self.parameters(),
            lr=1e-3,
            weight_decay=1e-2)
        scheduler = optim.lr_scheduler.CosineAnnealingLR(
            optimizer,
            T_max=10,
            eta_min=1e-4)
        return [optimizer], [scheduler]

    def training_step(self, batch, batch_idx):
        self.model.autoencoder.eval()
        x, y, mask = batch
        data = torch.cat([x, y], dim=1)
        z1 = self.model.autoencoder.encode(data)
        pred, z2 = self.model(x, mask)
        loss, full_state_loss, latent_loss = self.compute_loss(data, pred, z1, z2)
        self.log('train/loss', loss)
        self.log('train/mse', full_state_loss)
        self.log('train/latent_mse', latent_loss)
        self.log('train/lr', self.trainer.optimizers[0].param_groups[0]['lr'])
        return loss

    def validation_step(self, batch, batch_idx):
        x, y, mask = batch
        data = torch.cat([x, y], dim=1)
        with torch.no_grad():
            z1 = self.model.autoencoder.encode(data)
            pred, z2 = self.model(x, mask)
            loss, full_state_loss, latent_loss = self.compute_loss(data, pred, z1, z2)
        self.log('val/loss', loss)
        self.log('val/mse', full_state_loss)
        self.log('val/latent_mse', latent_loss)
        return loss

    def test_step(self, batch, batch_idx):
        x, y, mask = batch
        data = torch.cat([x, y], dim=1)
        with torch.no_grad():
            z1 = self.model.autoencoder.encode(data)
            pred, z2 = self.model(x, mask)
            loss, full_state_loss, latent_loss = self.compute_loss(data, pred, z1, z2)
        self.log('test/loss', loss)
        self.log('test/mse', full_state_loss)
        self.log('test/latent_mse', latent_loss)
        return loss

    def predict_step(self, batch, batch_idx):
        x, y, mask = batch

        batch_size = len(x)
        os.makedirs('logs/timae/output', exist_ok=True)

        with torch.no_grad():
            pred, _ = self.model(x, mask)

        for i in range(batch_size):
            if batch_idx*batch_size+i >= self.visulise_num:
                break
            ShallowWaterDataset.visualise_sequence(
                torch.cat([x[i], y[i]], dim=0),
                save_path=f'logs/timae/output/input_{batch_idx*batch_size+i}.png'
            )
            ShallowWaterDataset.visualise_sequence(
                pred[i],
                save_path=f'logs/timae/output/predict_{batch_idx*batch_size+i}.png'
            )
        return pred

    def compute_loss(self, x, pred, z1=None, z2=None):
        full_state_loss = F.mse_loss(pred, x)
        if z1 is None or z2 is None:
            return full_state_loss

        latent_loss = F.mse_loss(z2, z1)

        loss = full_state_loss / (torch.linalg.norm(x) / x.numel() + 1e-8) + latent_loss / (torch.linalg.norm(z1) / z1.numel() + 1e-8)
        return loss, full_state_loss, latent_loss