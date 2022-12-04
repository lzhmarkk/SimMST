from __future__ import division
import torch
import torch.nn as nn
from .TemporalMixer import TemporalMixer
from .SpatialMixer import SpatialMixer


class CRGNNBlock(nn.Module):
    def __init__(self, device, num_nodes, gcn_depth, dropout, propalpha, residual_channels, conv_channels,
                 temporal_func, dilation, begin_length, end_length):
        super(CRGNNBlock, self).__init__()
        self.device = device
        self.layer_norm_affine = True

        self.temporal_mixer = TemporalMixer(device=device, temporal_func=temporal_func,
                                            residual_channels=residual_channels, conv_channels=conv_channels,
                                            dilation=dilation, begin_dim=begin_length, end_dim=end_length,
                                            dropout=dropout)
        self.spatial_mixer = nn.ModuleList([
            SpatialMixer(conv_channels, residual_channels, gcn_depth, dropout, propalpha),
            SpatialMixer(conv_channels, residual_channels, gcn_depth, dropout, propalpha)
        ])
        self.channel_mixer = torch.nn.Conv2d(conv_channels, residual_channels,
                                             kernel_size=(1, 1), padding=(0, 0), stride=(1, 1), bias=True)

        self.temporal_norm = nn.LayerNorm([residual_channels, num_nodes, end_length],
                                          elementwise_affine=self.layer_norm_affine)
        self.channel_norm = nn.LayerNorm([residual_channels, num_nodes, end_length],
                                         elementwise_affine=self.layer_norm_affine)

    def temporal_layer(self, x):
        h = self.temporal_mixer(x)
        h = h + x[..., -h.shape[-1]:]
        h = self.temporal_norm(h)  # todo layer norm the last dimension
        return h

    def spatial_layer(self, x, g):
        h = self.spatial_mixer[0](x, g) + self.spatial_mixer[1](x, g.transpose(1, 0))
        return h

    def channel_layer(self, x):
        h = self.channel_mixer(x)
        h = h + x
        h = self.channel_norm(h)
        return h


class CRGNN(nn.Module):
    def __init__(self, device, num_nodes, gcn_depth, dropout, input_dim, output_dim,
                 window, horizon, propalpha, dilation_exponential,
                 layers, residual_channels, conv_channels, skip_channels, end_channels, temporal_func):
        super(CRGNN, self).__init__()
        self.device = device
        self.num_nodes = num_nodes

        self.mixer_layers = nn.ModuleList()
        self.skip_convs = nn.ModuleList()

        # modules
        self.start_conv = nn.Conv2d(in_channels=input_dim, out_channels=residual_channels, kernel_size=(1, 1))

        kernel_size = 7
        rf_size_i = 1
        if dilation_exponential > 1:
            self.receptive_field = int(1 + (kernel_size - 1) * (dilation_exponential ** layers - 1) / (
                    dilation_exponential - 1))
        else:
            self.receptive_field = layers * (kernel_size - 1) + 1

        length = max(self.receptive_field, window)  # todo unnecessarily pad sequence when use mlp
        self.skip0 = nn.Conv2d(in_channels=input_dim, out_channels=skip_channels,
                               kernel_size=(1, length), bias=True)

        # layers
        dilation = 1
        for j in range(1, layers + 1):
            if dilation_exponential > 1:
                rf_size_j = int(rf_size_i + (kernel_size - 1) *
                                (dilation_exponential ** j - 1) / (dilation_exponential - 1))
            else:
                rf_size_j = rf_size_i + j * (kernel_size - 1)

            begin_length = length - (rf_size_j - (kernel_size - 1)) + 1
            end_length = length - rf_size_j + 1

            self.mixer_layers.append(CRGNNBlock(device=device, num_nodes=num_nodes, gcn_depth=gcn_depth,
                                                dropout=dropout, propalpha=propalpha,
                                                residual_channels=residual_channels,
                                                conv_channels=conv_channels,
                                                temporal_func=temporal_func, dilation=dilation,
                                                begin_length=begin_length, end_length=end_length))

            self.skip_convs.append(nn.Conv2d(in_channels=conv_channels,
                                             out_channels=skip_channels,
                                             kernel_size=(1, end_length), bias=True))

            dilation *= dilation_exponential

        # skip connection
        end_length = max(1, window - self.receptive_field + 1)
        # self.skipE = nn.Conv2d(in_channels=residual_channels, out_channels=skip_channels,
        #                        kernel_size=(1, end_length), bias=True)

        # final output
        self.end_conv = nn.Sequential(nn.Conv2d(in_channels=3 * skip_channels,
                                                out_channels=end_channels,
                                                kernel_size=(1, 1),
                                                bias=True),
                                      nn.ReLU(),
                                      nn.Conv2d(in_channels=end_channels,
                                                out_channels=horizon * output_dim,
                                                kernel_size=(1, 1),
                                                bias=True))

    def temporal_layer(self, x, l):
        return self.mixer_layers[l].temporal_layer(x)

    def spatial_layer(self, x, g, l):
        return self.mixer_layers[l].spatial_layer(x, g)

    def channel_layer(self, x, l):
        return self.mixer_layers[l].channel_layer(x)

    def forward(self, x):
        raise NotImplementedError()
