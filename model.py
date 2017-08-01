from __future__ import division
import os
import time
import math
from glob import glob
import tensorflow as tf
import numpy as np
from six.moves import xrange

from ops import *
from utils import *

def conv_out_size_same(size, stride):
  return int(math.ceil(float(size) / float(stride)))

class DCGAN(object):
  def __init__(self, sess, input_height=108, input_width=108, crop=True,
         batch_size=64, sample_num = 64, output_height=64, output_width=64,
         y_dim=None, z_dim=100, gf_dim=64, df_dim=64,
         gfc_dim=1024, dfc_dim=1024, c_dim=3, dataset_name='default',
         input_fname_pattern='*.jpg', checkpoint_dir=None, sample_dir=None,FLAGS=None,n_hidden_recog_2=256):
    """

    Args:
      sess: TensorFlow session
      batch_size: The size of batch. Should be specified before training.
      y_dim: (optional) Dimension of dim for y. [None]
      z_dim: (optional) Dimension of dim for Z. [100]
      gf_dim: (optional) Dimension of gen filters in first conv layer. [64]
      df_dim: (optional) Dimension of discrim filters in first conv layer. [64]
      gfc_dim: (optional) Dimension of gen units for for fully connected layer. [1024]
      dfc_dim: (optional) Dimension of discrim units for fully connected layer. [1024]
      c_dim: (optional) Dimension of image color. For grayscale input, set to 1. [3]
    """
    self.sess = sess
    self.crop = crop
    self.FLAGS = FLAGS
    self.batch_size = batch_size
    self.sample_num = sample_num

    self.input_height = input_height
    self.input_width = input_width
    self.output_height = output_height
    self.output_width = output_width

    self.y_dim = y_dim
    self.z_dim = z_dim
    self.n_hidden_recog_2=n_hidden_recog_2
    self.gf_dim = gf_dim
    self.df_dim = df_dim

    self.gfc_dim = gfc_dim
    self.dfc_dim = dfc_dim

    # batch normalization : deals with poor initialization helps gradient flow
    self.d_bn1 = batch_norm(name='d_bn1')
    self.d_bn2 = batch_norm(name='d_bn2')

    if not self.y_dim:
      self.d_bn3 = batch_norm(name='d_bn3')

    self.g_bn0 = batch_norm(name='g_bn0')
    self.g_bn1 = batch_norm(name='g_bn1')
    self.g_bn2 = batch_norm(name='g_bn2')

    if not self.y_dim:
      self.g_bn3 = batch_norm(name='g_bn3')

    self.dataset_name = dataset_name
    self.input_fname_pattern = input_fname_pattern
    self.checkpoint_dir = checkpoint_dir

    if self.dataset_name == 'mnist':
      self.data_X, self.data_y = self.load_mnist()
      self.c_dim = self.data_X[0].shape[-1]
    else:
      self.data = glob(os.path.join("./data", self.dataset_name, self.input_fname_pattern))
      imreadImg = imread(self.data[0]);
      if len(imreadImg.shape) >= 3: #check if image is a non-grayscale image by checking channel number
        self.c_dim = imread(self.data[0]).shape[-1]
      else:
        self.c_dim = 1

    self.grayscale = (self.c_dim == 1)

    self.build_model()

  def build_model(self):
    if self.y_dim:
      self.y= tf.placeholder(tf.float32, [self.batch_size, self.y_dim], name='y')

    if self.crop:
      image_dims = [self.output_height, self.output_width, self.c_dim]
    else:
      image_dims = [self.input_height, self.input_width, self.c_dim]

    self.inputs = tf.placeholder(
      tf.float32, [self.batch_size] + image_dims, name='real_images')

    inputs = self.inputs

    self.z = tf.placeholder(
      tf.float32, [None, self.z_dim], name='z')
    self.z_sum = histogram_summary("z", self.z)

    if self.y_dim:
      self.G = self.generator(self.z, self.y)
      self.D, self.D_logits = \
          self.discriminator(inputs, self.y, reuse=False)

      self.sampler = self.sampler(self.z, self.y)
      self.D_, self.D_logits_ = \
          self.discriminator(self.G, self.y, reuse=True)
    else:
      self.z_mean, self.z_log_sigma_sq = self.encoder(self.inputs,reuse=False)
      eps = tf.random_normal((self.batch_size, self.z_dim), 0, 1, dtype=tf.float32)
      # z = mu + sigma*epsilon
      self.E = tf.add(self.z_mean, tf.multiply(tf.sqrt(tf.exp(self.z_log_sigma_sq)), eps))
      self.inputs_= self.generator(self.E)
      self.G = self.generator(self.z,reuse=True)
      self.D, self.D_logits = self.discriminator(self.inputs)
      self.D2, self.D_logits2 = self.discriminator(self.inputs_,reuse=True)
      
      self.sampler = self.sampler(self.z)
      self.D_, self.D_logits_ = self.discriminator(self.G, reuse=True)
    if self.FLAGS.W_GAN is False:
        self.d_sum = histogram_summary("d", self.D)
        self.d__sum = histogram_summary("d_", self.D_)
        self.G_sum = image_summary("G", self.G)
    else:
        self.d_sum = histogram_summary("d", self.D_logits)
        self.d__sum = histogram_summary("d_", self.D_logits_)
        self.G_sum = image_summary("G", self.G)

    def sigmoid_cross_entropy_with_logits(x, y):
      try:
        return tf.nn.sigmoid_cross_entropy_with_logits(logits=x, labels=y)
      except:
        return tf.nn.sigmoid_cross_entropy_with_logits(logits=x, targets=y)
    if self.FLAGS.W_GAN is True:
        # Standard WGAN loss
            self.g_loss = -0.5*tf.reduce_mean(self.D_logits_) -0.5* tf.reduce_mean(self.D_logits2)
            self.d_loss = 0.5*tf.reduce_mean(self.D_logits_) - tf.reduce_mean(self.D_logits) +0.5*tf.reduce_mean(self.D_logits2)
            self.w_distance = self.d_loss
            # Gradient penalty
            alpha = tf.random_uniform(
                shape=[self.batch_size,1], 
                minval=0.,
                maxval=1.
            )
            differences = tf.reshape(self.inputs_ - inputs,[self.batch_size,-1])
            interpolates = tf.reshape(inputs,[self.batch_size,-1]) + (alpha*differences)
            interpolates = tf.reshape(interpolates,inputs.get_shape())
            _ ,d_image = self.discriminator(interpolates,reuse=True)
            gradients = tf.gradients(d_image, [interpolates])[0]
            slopes = tf.sqrt(tf.reduce_sum(tf.square(gradients), reduction_indices=[1]))
            gradient_penalty = tf.reduce_mean((slopes-1.)**2)
            self.d_loss += self.FLAGS.LAMBDA*gradient_penalty
            differences = tf.reshape(self.G - inputs,[self.batch_size,-1])
            interpolates = tf.reshape(inputs,[self.batch_size,-1]) + (alpha*differences)
            interpolates = tf.reshape(interpolates,inputs.get_shape())
            _ ,d_image = self.discriminator(interpolates,reuse=True)
            gradients = tf.gradients(d_image, [interpolates])[0]
            slopes = tf.sqrt(tf.reduce_sum(tf.square(gradients), reduction_indices=[1]))
            gradient_penalty = tf.reduce_mean((slopes-1.)**2)
            self.d_loss += self.FLAGS.LAMBDA*gradient_penalty

            # The loss is composed of two terms:
            # 1.) The reconstruction loss (the negative log probability
            #     of the input under the reconstructed Bernoulli distribution 
            #     induced by the decoder in the data space).
            #     This can be interpreted as the number of "nats" required
            #     for reconstructing the input when the activation in latent
            #     is given.
            # Adding 1e-10 to avoid evaluation of log(0.0)
            self.reconstr_loss =  tf.reduce_sum(tf.square(self.inputs-self.inputs_),
                               [1,2,3])
            # 2.) The latent loss, which is defined as the Kullback Leibler divergence 
            ##    between the distribution in latent space induced by the encoder on 
            #     the data and some prior. This acts as a kind of regularizer.
            #     This can be interpreted as the number of "nats" required
            #     for transmitting the the latent space distribution given
            #     the prior.
            self.latent_loss = -0.5 * tf.reduce_sum(1 + self.z_log_sigma_sq 
                                               - tf.square(self.z_mean) 
                                               - tf.exp(self.z_log_sigma_sq), 1)
            self.e_loss = self.FLAGS.GAMMA * tf.reduce_mean(self.reconstr_loss + self.latent_loss)
            self.g_loss = self.g_loss + self.FLAGS.GAMMA * tf.reduce_mean(self.reconstr_loss)

    else:
        self.d_loss_real = tf.reduce_mean(
          sigmoid_cross_entropy_with_logits(self.D_logits, tf.ones_like(self.D)))
        self.d_loss_fake1 = tf.reduce_mean(
          sigmoid_cross_entropy_with_logits(self.D_logits_, tf.zeros_like(self.D_)))
        self.d_loss_fake2 = tf.reduce_mean(
          sigmoid_cross_entropy_with_logits(self.D_logits2, tf.zeros_like(self.D2)))
        self.d_loss_fake = self.d_loss_fake1 + self.d_loss_fake2
        self.g_loss1 = tf.reduce_mean(
          sigmoid_cross_entropy_with_logits(self.D_logits_, tf.ones_like(self.D_)))
        self.g_loss2 = tf.reduce_mean(
          sigmoid_cross_entropy_with_logits(self.D_logits2, tf.ones_like(self.D2)))
        self.g_loss = self.g_loss1 + self.g_loss2
        self.d_loss_real_sum = scalar_summary("d_loss_real", self.d_loss_real)
        self.d_loss_fake_sum = scalar_summary("d_loss_fake", self.d_loss_fake)
                              
        self.d_loss = self.d_loss_real + self.d_loss_fake
        # The loss is composed of two terms:
        # 1.) The reconstruction loss (the negative log probability
        #     of the input under the reconstructed Bernoulli distribution 
        #     induced by the decoder in the data space).
        #     This can be interpreted as the number of "nats" required
        #     for reconstructing the input when the activation in latent
        #     is given.
        # Adding 1e-10 to avoid evaluation of log(0.0)
        reconstr_loss =  tf.reduce_sum(tf.square(self.inputs-self.inputs_),
                           [1,2,3])
        # 2.) The latent loss, which is defined as the Kullback Leibler divergence 
        ##    between the distribution in latent space induced by the encoder on 
        #     the data and some prior. This acts as a kind of regularizer.
        #     This can be interpreted as the number of "nats" required
        #     for transmitting the the latent space distribution given
        #     the prior.
        latent_loss = -0.5 * tf.reduce_sum(1 + self.z_log_sigma_sq 
                                           - tf.square(self.z_mean) 
                                           - tf.exp(self.z_log_sigma_sq), 1)
        self.e_loss = tf.reduce_mean(reconstr_loss + latent_loss)
        self.g_loss = self.g_loss + self.FLAGS.GAMMA * tf.reduce_mean(reconstr_loss)
    self.g_loss_sum = scalar_summary("g_loss", self.g_loss)
    self.d_loss_sum = scalar_summary("d_loss", self.d_loss)
    self.e_loss_sum = scalar_summary("e_loss", self.e_loss)
    t_vars = tf.trainable_variables()

    self.d_vars = [var for var in t_vars if 'd_' in var.name]
    self.g_vars = [var for var in t_vars if 'g_' in var.name]
    self.e_vars = [var for var in t_vars if 'e_' in var.name]
    self.saver = tf.train.Saver()


  def train(self, config):
    if self.FLAGS.W_GAN is False:
        d_optim = tf.train.AdamOptimizer(config.learning_rate, beta1=config.beta1) \
                  .minimize(self.d_loss, var_list=self.d_vars)
        g_optim = tf.train.AdamOptimizer(config.learning_rate, beta1=config.beta1) \
                  .minimize(self.g_loss, var_list=self.g_vars)
        e_optim = tf.train.AdamOptimizer(config.learning_rate, beta1=config.beta1) \
                  .minimize(self.e_loss, var_list=self.e_vars)
    else:
        d_optim = tf.train.AdamOptimizer(config.learning_rate, beta1=config.beta1,beta2=0.9) \
                  .minimize(self.d_loss, var_list=self.d_vars)
        g_optim = tf.train.AdamOptimizer(config.learning_rate, beta1=config.beta1,beta2=0.9) \
                  .minimize(self.g_loss, var_list=self.g_vars)
        e_optim = tf.train.AdamOptimizer(config.learning_rate, beta1=config.beta1,beta2=0.9) \
                  .minimize(self.e_loss, var_list=self.e_vars)

    try:
      tf.global_variables_initializer().run()
    except:
      tf.initialize_all_variables().run()
    if self.FLAGS.W_GAN is True:
        self.g_sum = merge_summary([self.z_sum, self.d__sum,
          self.G_sum, self.g_loss_sum])
        self.d_sum = merge_summary(
            [self.z_sum, self.d_sum,  self.d_loss_sum])
    else:
        self.g_sum = merge_summary([self.z_sum, self.d__sum,
          self.G_sum, self.d_loss_fake_sum, self.g_loss_sum])
        self.d_sum = merge_summary(
            [self.z_sum, self.d_sum, self.d_loss_real_sum, self.d_loss_sum])
    self.writer = SummaryWriter("./logs", self.sess.graph)

    sample_z = np.random.normal(size=(self.sample_num , self.z_dim))
    
    if config.dataset == 'mnist':
      sample_inputs = self.data_X[0:self.sample_num]
      sample_labels = self.data_y[0:self.sample_num]
    else:
      sample_files = self.data[0:self.sample_num]
      sample = [
          get_image(sample_file,
                    input_height=self.input_height,
                    input_width=self.input_width,
                    resize_height=self.output_height,
                    resize_width=self.output_width,
                    crop=self.crop,
                    grayscale=self.grayscale) for sample_file in sample_files]
      if (self.grayscale):
        sample_inputs = np.array(sample).astype(np.float32)[:, :, :, None]
      else:
        sample_inputs = np.array(sample).astype(np.float32)
  
    counter = 1
    start_time = time.time()
    could_load, checkpoint_counter = self.load(self.checkpoint_dir)
    if could_load:
      counter = checkpoint_counter
      print(" [*] Load SUCCESS")
    else:
      print(" [!] Load failed...")

    for epoch in xrange(config.epoch):
      if config.dataset == 'mnist':
        batch_idxs = min(len(self.data_X), config.train_size) // config.batch_size
      else:      
        self.data = glob(os.path.join(
          "./data", config.dataset, self.input_fname_pattern))
        batch_idxs = min(len(self.data), config.train_size) // config.batch_size

      for idx in xrange(0, batch_idxs):
        if config.dataset == 'mnist':
          batch_images = self.data_X[idx*config.batch_size:(idx+1)*config.batch_size]
          batch_labels = self.data_y[idx*config.batch_size:(idx+1)*config.batch_size]
        else:
          batch_files = self.data[idx*config.batch_size:(idx+1)*config.batch_size]
          batch = [
              get_image(batch_file,
                        input_height=self.input_height,
                        input_width=self.input_width,
                        resize_height=self.output_height,
                        resize_width=self.output_width,
                        crop=self.crop,
                        grayscale=self.grayscale) for batch_file in batch_files]
          if self.grayscale:
            batch_images = np.array(batch).astype(np.float32)[:, :, :, None]
          else:
            batch_images = np.array(batch).astype(np.float32)

        batch_z = np.random.normal(size=[config.batch_size, self.z_dim]) \
              .astype(np.float32)
        if self.FLAGS.W_GAN is False:
            if config.dataset == 'mnist':
              # Update D network
              _, summary_str = self.sess.run([d_optim, self.d_sum],
                feed_dict={ 
                  self.inputs: batch_images,
                  self.z: batch_z,
                  self.y:batch_labels,
                })
              self.writer.add_summary(summary_str, counter)

              # Update G network
              _, summary_str = self.sess.run([g_optim, self.g_sum],
                feed_dict={
                  self.z: batch_z, 
                  self.y:batch_labels,
                })
              self.writer.add_summary(summary_str, counter)

              # Run g_optim twice to make sure that d_loss does not go to zero (different from paper)
              _, summary_str = self.sess.run([g_optim, self.g_sum],
                feed_dict={ self.z: batch_z, self.y:batch_labels })
              self.writer.add_summary(summary_str, counter)
              
              errD_fake = self.d_loss_fake.eval({
                  self.z: batch_z, 
                  self.y:batch_labels
              })
              errD_real = self.d_loss_real.eval({
                  self.inputs: batch_images,
                  self.y:batch_labels
              })
              errG = self.g_loss.eval({
                  self.z: batch_z,
                  self.y: batch_labels
              })
            else:
              #print batch_images.dtype
              # Update E network
              self.sess.run([e_optim],
                feed_dict={ self.inputs: batch_images})


              # Update G network
              _, summary_str = self.sess.run([g_optim, self.g_sum],
                feed_dict={ self.z: batch_z ,self.inputs: batch_images})
              self.writer.add_summary(summary_str, counter)
              # Run g_optim twice to make sure that d_loss does not go to zero (different from paper)
              _, summary_str = self.sess.run([g_optim, self.g_sum],
                feed_dict={ self.z: batch_z ,self.inputs: batch_images})
              self.writer.add_summary(summary_str, counter)
              # Update D network
              _, summary_str = self.sess.run([d_optim, self.d_sum],
                feed_dict={ self.inputs: batch_images, self.z: batch_z })
              self.writer.add_summary(summary_str, counter)


              
              errD_fake = self.d_loss_fake.eval({ self.z: batch_z,self.inputs: batch_images })
              errD_real = self.d_loss_real.eval({ self.inputs: batch_images })
              errG = self.g_loss.eval({self.z: batch_z,self.inputs: batch_images})
              errE = self.e_loss.eval({self.inputs: batch_images })
        else:
            if config.dataset == 'mnist':
              for _ in range(self.FLAGS.CRITIC_NUM):
                  # Update D network
                  _, summary_str = self.sess.run([d_optim, self.d_sum],
                    feed_dict={ 
                      self.inputs: batch_images,
                      self.z: batch_z,
                      self.y:batch_labels,
                    })
              self.writer.add_summary(summary_str, counter)

              # Update G network
              _, summary_str = self.sess.run([g_optim, self.g_sum],
                feed_dict={
                  self.z: batch_z, 
                  self.y:batch_labels,
                })
              self.writer.add_summary(summary_str, counter)

              errD = self.d_loss.eval({
                  self.z: batch_z, 
                  self.y:batch_labels,
                  self.inputs: batch_images
              })
              errG = self.g_loss.eval({
                  self.z: batch_z,
                  self.y: batch_labels
              })
            else:

              for _ in range(self.FLAGS.CRITIC_NUM):

                  # Update D network
                  _, summary_str = self.sess.run([d_optim, self.d_sum],
                    feed_dict={ self.inputs: batch_images, self.z: batch_z })
              self.writer.add_summary(summary_str, counter)
              # Update E network
              self.sess.run([e_optim],feed_dict={ self.inputs: batch_images})
              # Update G network
              _, summary_str = self.sess.run([g_optim, self.g_sum],
                feed_dict={  self.z: batch_z ,self.inputs: batch_images })
              
              self.writer.add_summary(summary_str, counter)

              errE = self.e_loss.eval({self.inputs: batch_images })
              errD = self.d_loss.eval({ self.z: batch_z ,self.inputs: batch_images})
              errG = self.g_loss.eval({ self.z: batch_z ,self.inputs: batch_images})
              err_rc = tf.reduce_mean(self.reconstr_loss).eval({self.inputs: batch_images })
              W_dis = self.w_distance.eval({ self.z: batch_z ,self.inputs: batch_images})
        counter += 1
        if self.FLAGS.W_GAN is False:
            print("Epoch: [%2d] [%4d/%4d] time: %4.4f, d_loss: %.8f, g_loss: %.8f, e_loss: %.8f" \
              % (epoch, idx, batch_idxs,
                time.time() - start_time, errD_fake+errD_real, errG, errE))
        else:
            print("Epoch: [%2d] [%4d/%4d] time: %4.4f, d_loss: %.8f, g_loss: %.8f, e_loss: %.8f, W_distance: %.8f, reconstruction_loss: %.8f"\
              % (epoch, idx, batch_idxs,
                time.time() - start_time, errD, errG, errE, W_dis , err_rc))
         
        if np.mod(counter, 100) == 1:
          if config.dataset == 'mnist':
            samples, d_loss, g_loss = self.sess.run(
              [self.sampler, self.d_loss, self.g_loss],
              feed_dict={
                  self.z: sample_z,
                  self.inputs: sample_inputs,
                  self.y:sample_labels,
              }
            )
            save_images(samples, image_manifold_size(samples.shape[0]),
                  './{}/train_{:02d}_{:04d}.png'.format(config.sample_dir, epoch, idx))
            print("[Sample] d_loss: %.8f, g_loss: %.8f" % (d_loss, g_loss)) 
          else:
            try:
              samples, d_loss, g_loss = self.sess.run(
                [self.sampler, self.d_loss, self.g_loss],
                feed_dict={
                    self.z: sample_z,
                    self.inputs: sample_inputs,
                },
              )
              save_images(samples, image_manifold_size(samples.shape[0]),
                    './{}/train_{:02d}_{:04d}.png'.format(config.sample_dir, epoch, idx))
              print("[Sample] d_loss: %.8f, g_loss: %.8f" % (d_loss, g_loss)) 
            except:
              print("one pic error!...")
            self.reconstruction(batch_images,config,epoch,idx)
        if np.mod(counter, 500) == 2:
          self.save(config.checkpoint_dir, counter)

  def discriminator(self, image, y=None, reuse=False):
    with tf.variable_scope("discriminator") as scope:
      if reuse:
        scope.reuse_variables()

      if not self.y_dim:
        h0 = lrelu(conv2d(image, self.df_dim, name='d_h0_conv'))
        if self.FLAGS.W_GAN is False:
            h1 = lrelu(self.d_bn1(conv2d(h0, self.df_dim*2, name='d_h1_conv')))
            h2 = lrelu(self.d_bn2(conv2d(h1, self.df_dim*4, name='d_h2_conv')))
            h3 = lrelu(self.d_bn3(conv2d(h2, self.df_dim*8, name='d_h3_conv')))
        else:
            h1 = lrelu(conv2d(h0, self.df_dim*2, name='d_h1_conv'))
            h2 = lrelu(conv2d(h1, self.df_dim*4, name='d_h2_conv'))
            h3 = lrelu(conv2d(h2, self.df_dim*8, name='d_h3_conv'))
        h4 = linear(tf.reshape(h3, [self.batch_size, -1]), 1, 'd_h4_lin')
        if self.FLAGS.W_GAN is False:
            return tf.nn.sigmoid(h4), h4
        else:
            return None,tf.reshape(h4, [-1])
      else:
        yb = tf.reshape(y, [self.batch_size, 1, 1, self.y_dim])
        x = conv_cond_concat(image, yb)

        h0 = lrelu(conv2d(x, self.c_dim + self.y_dim, name='d_h0_conv'))
        h0 = conv_cond_concat(h0, yb)
        if self.FLAGS.W_GAN is False:
            h1 = lrelu(self.d_bn1(conv2d(h0, self.df_dim + self.y_dim, name='d_h1_conv')))
        else:
            h1 = lrelu(conv2d(h0, self.df_dim + self.y_dim, name='d_h1_conv'))
        h1 = tf.reshape(h1, [self.batch_size, -1])      
        h1 = concat([h1, y], 1)
        if self.FLAGS.W_GAN is False:        
            h2 = lrelu(self.d_bn2(linear(h1, self.dfc_dim, 'd_h2_lin')))
        else:
            h2 = lrelu(linear(h1, self.dfc_dim, 'd_h2_lin'))
        h2 = concat([h2, y], 1)

        h3 = linear(h2, 1, 'd_h3_lin')
        if self.FLAGS.W_GAN is False:
            return tf.nn.sigmoid(h3), h3
        else:
            return None,tf.reshape(h3, [-1])
  def generator(self, z, y=None,reuse = False):
    with tf.variable_scope("generator") as scope:
      if reuse:
        scope.reuse_variables()
      if not self.y_dim:
        s_h, s_w = self.output_height, self.output_width
        s_h2, s_w2 = conv_out_size_same(s_h, 2), conv_out_size_same(s_w, 2)
        s_h4, s_w4 = conv_out_size_same(s_h2, 2), conv_out_size_same(s_w2, 2)
        s_h8, s_w8 = conv_out_size_same(s_h4, 2), conv_out_size_same(s_w4, 2)
        s_h16, s_w16 = conv_out_size_same(s_h8, 2), conv_out_size_same(s_w8, 2)

        # project `z` and reshape
        self.z_, self.h0_w, self.h0_b = linear(
            z, self.gf_dim*8*s_h16*s_w16, 'g_h0_lin', with_w=True)

        self.h0 = tf.reshape(
            self.z_, [-1, s_h16, s_w16, self.gf_dim * 8])
        h0 = tf.nn.relu(self.g_bn0(self.h0))

        self.h1, self.h1_w, self.h1_b = deconv2d(
            h0, [self.batch_size, s_h8, s_w8, self.gf_dim*4], name='g_h1', with_w=True)
        h1 = tf.nn.relu(self.g_bn1(self.h1))

        h2, self.h2_w, self.h2_b = deconv2d(
            h1, [self.batch_size, s_h4, s_w4, self.gf_dim*2], name='g_h2', with_w=True)
        h2 = tf.nn.relu(self.g_bn2(h2))

        h3, self.h3_w, self.h3_b = deconv2d(
            h2, [self.batch_size, s_h2, s_w2, self.gf_dim*1], name='g_h3', with_w=True)
        h3 = tf.nn.relu(self.g_bn3(h3))

        h4, self.h4_w, self.h4_b = deconv2d(
            h3, [self.batch_size, s_h, s_w, self.c_dim], name='g_h4', with_w=True)

        return tf.nn.tanh(h4)
      else:
        s_h, s_w = self.output_height, self.output_width
        s_h2, s_h4 = int(s_h/2), int(s_h/4)
        s_w2, s_w4 = int(s_w/2), int(s_w/4)

        # yb = tf.expand_dims(tf.expand_dims(y, 1),2)
        yb = tf.reshape(y, [self.batch_size, 1, 1, self.y_dim])
        z = concat([z, y], 1)

        h0 = tf.nn.relu(
            self.g_bn0(linear(z, self.gfc_dim, 'g_h0_lin')))
        h0 = concat([h0, y], 1)

        h1 = tf.nn.relu(self.g_bn1(
            linear(h0, self.gf_dim*2*s_h4*s_w4, 'g_h1_lin')))
        h1 = tf.reshape(h1, [self.batch_size, s_h4, s_w4, self.gf_dim * 2])

        h1 = conv_cond_concat(h1, yb)

        h2 = tf.nn.relu(self.g_bn2(deconv2d(h1,
            [self.batch_size, s_h2, s_w2, self.gf_dim * 2], name='g_h2')))
        h2 = conv_cond_concat(h2, yb)

        return tf.nn.sigmoid(
            deconv2d(h2, [self.batch_size, s_h, s_w, self.c_dim], name='g_h3'))
  def xavier_init(self,fan_in, fan_out, constant=1): 
        """ Xavier initialization of network weights"""
        # https://stackoverflow.com/questions/33640581/how-to-do-xavier-initialization-on-tensorflow
        low = -constant*np.sqrt(6.0/(fan_in + fan_out)) 
        high = constant*np.sqrt(6.0/(fan_in + fan_out))
        return tf.random_uniform((fan_in, fan_out), 
                                 minval=low, maxval=high, 
                                 dtype=tf.float32)
  
  def encoder(self,image,reuse=False):
        with tf.variable_scope("encoder") as scope:
            if reuse:
                scope.reuse_variables()
            # Generate probabilistic encoder (recognition network), which
            # maps inputs onto a normal distribution in latent space.
            # The transformation is parametrized and can be learned.
            weights = {
            'out_mean': tf.Variable(self.xavier_init(self.n_hidden_recog_2, self.z_dim),"e_weight_out_mean"),
            'out_log_sigma': tf.Variable(self.xavier_init(self.n_hidden_recog_2, self.z_dim),"e_weight_out_log_sigma")}
            biases = {
            'out_mean': tf.Variable(tf.zeros([self.z_dim], dtype=tf.float32),"e_bias_out_mean"),
            'out_log_sigma': tf.Variable(tf.zeros([self.z_dim], dtype=tf.float32),"e_bias_out_log_sigma")}
            h0 = tf.nn.relu(conv2d(image, self.df_dim, name='e_h0_conv'))    #out 16*16*32
            h1 = tf.nn.relu(conv2d(h0, self.df_dim*2, name='e_h1_conv'))
            h2 = tf.nn.relu(conv2d(h1, self.df_dim*4, name='e_h2_conv'))
            h3 = tf.nn.relu(conv2d(h2, self.df_dim*8, name='e_h3_conv'))
            h4 = linear(tf.reshape(h3, [self.batch_size, -1]), self.n_hidden_recog_2, 'e_h4_lin')
            z_mean = tf.add(tf.matmul(h4, weights['out_mean']),
                            biases['out_mean'])
            z_log_sigma_sq =                 tf.add(tf.matmul(h4, weights['out_log_sigma']), 
                       biases['out_log_sigma'])
            return (z_mean, z_log_sigma_sq)  
  def sampler(self, z, y=None):
    with tf.variable_scope("generator") as scope:
      scope.reuse_variables()

      if not self.y_dim:
        s_h, s_w = self.output_height, self.output_width
        s_h2, s_w2 = conv_out_size_same(s_h, 2), conv_out_size_same(s_w, 2)
        s_h4, s_w4 = conv_out_size_same(s_h2, 2), conv_out_size_same(s_w2, 2)
        s_h8, s_w8 = conv_out_size_same(s_h4, 2), conv_out_size_same(s_w4, 2)
        s_h16, s_w16 = conv_out_size_same(s_h8, 2), conv_out_size_same(s_w8, 2)

        # project `z` and reshape
        h0 = tf.reshape(
            linear(z, self.gf_dim*8*s_h16*s_w16, 'g_h0_lin'),
            [-1, s_h16, s_w16, self.gf_dim * 8])
        h0 = tf.nn.relu(self.g_bn0(h0, train=False))

        h1 = deconv2d(h0, [self.batch_size, s_h8, s_w8, self.gf_dim*4], name='g_h1')
        h1 = tf.nn.relu(self.g_bn1(h1, train=False))

        h2 = deconv2d(h1, [self.batch_size, s_h4, s_w4, self.gf_dim*2], name='g_h2')
        h2 = tf.nn.relu(self.g_bn2(h2, train=False))

        h3 = deconv2d(h2, [self.batch_size, s_h2, s_w2, self.gf_dim*1], name='g_h3')
        h3 = tf.nn.relu(self.g_bn3(h3, train=False))

        h4 = deconv2d(h3, [self.batch_size, s_h, s_w, self.c_dim], name='g_h4')

        return tf.nn.tanh(h4)
      else:
        s_h, s_w = self.output_height, self.output_width
        s_h2, s_h4 = int(s_h/2), int(s_h/4)
        s_w2, s_w4 = int(s_w/2), int(s_w/4)

        # yb = tf.reshape(y, [-1, 1, 1, self.y_dim])
        yb = tf.reshape(y, [self.batch_size, 1, 1, self.y_dim])
        z = concat([z, y], 1)

        h0 = tf.nn.relu(self.g_bn0(linear(z, self.gfc_dim, 'g_h0_lin'), train=False))
        h0 = concat([h0, y], 1)

        h1 = tf.nn.relu(self.g_bn1(
            linear(h0, self.gf_dim*2*s_h4*s_w4, 'g_h1_lin'), train=False))
        h1 = tf.reshape(h1, [self.batch_size, s_h4, s_w4, self.gf_dim * 2])
        h1 = conv_cond_concat(h1, yb)

        h2 = tf.nn.relu(self.g_bn2(
            deconv2d(h1, [self.batch_size, s_h2, s_w2, self.gf_dim * 2], name='g_h2'), train=False))
        h2 = conv_cond_concat(h2, yb)

        return tf.nn.sigmoid(deconv2d(h2, [self.batch_size, s_h, s_w, self.c_dim], name='g_h3'))

  def load_mnist(self):
    data_dir = os.path.join("./data", self.dataset_name)
    
    fd = open(os.path.join(data_dir,'train-images-idx3-ubyte'))
    loaded = np.fromfile(file=fd,dtype=np.uint8)
    trX = loaded[16:].reshape((60000,28,28,1)).astype(np.float)

    fd = open(os.path.join(data_dir,'train-labels-idx1-ubyte'))
    loaded = np.fromfile(file=fd,dtype=np.uint8)
    trY = loaded[8:].reshape((60000)).astype(np.float)

    fd = open(os.path.join(data_dir,'t10k-images-idx3-ubyte'))
    loaded = np.fromfile(file=fd,dtype=np.uint8)
    teX = loaded[16:].reshape((10000,28,28,1)).astype(np.float)

    fd = open(os.path.join(data_dir,'t10k-labels-idx1-ubyte'))
    loaded = np.fromfile(file=fd,dtype=np.uint8)
    teY = loaded[8:].reshape((10000)).astype(np.float)

    trY = np.asarray(trY)
    teY = np.asarray(teY)
    
    X = np.concatenate((trX, teX), axis=0)
    y = np.concatenate((trY, teY), axis=0).astype(np.int)
    
    seed = 547
    np.random.seed(seed)
    np.random.shuffle(X)
    np.random.seed(seed)
    np.random.shuffle(y)
    
    y_vec = np.zeros((len(y), self.y_dim), dtype=np.float)
    for i, label in enumerate(y):
      y_vec[i,y[i]] = 1.0
    
    return X/255.,y_vec

  @property
  def model_dir(self):
    return "{}_{}_{}_{}".format(
        self.dataset_name, self.batch_size,
        self.output_height, self.output_width)
      
  def save(self, checkpoint_dir, step):
    model_name = "DCGAN.model"
    checkpoint_dir = os.path.join(checkpoint_dir, self.model_dir)

    if not os.path.exists(checkpoint_dir):
      os.makedirs(checkpoint_dir)

    self.saver.save(self.sess,
            os.path.join(checkpoint_dir, model_name),
            global_step=step)

  def load(self, checkpoint_dir):
    import re
    print(" [*] Reading checkpoints...")
    checkpoint_dir = os.path.join(checkpoint_dir, self.model_dir)

    ckpt = tf.train.get_checkpoint_state(checkpoint_dir)
    if ckpt and ckpt.model_checkpoint_path:
      ckpt_name = os.path.basename(ckpt.model_checkpoint_path)
      self.saver.restore(self.sess, os.path.join(checkpoint_dir, ckpt_name))
      counter = int(next(re.finditer("(\d+)(?!.*\d)",ckpt_name)).group(0))
      print(" [*] Success to read {}".format(ckpt_name))
      return True, counter
    else:
      print(" [*] Failed to find a checkpoint")
      return False, 0
  def reconstruction(self,image,config,epoch,idx):
      z_mean, z_log_sigma_sq = self.sess.run([self.z_mean, self.z_log_sigma_sq],feed_dict={
                    self.inputs: image
                })
      eps = np.random.normal(size=[config.batch_size, self.z_dim]) \
              .astype(np.float32)
      # z = mu + sigma*epsilon
      sample_z = (z_mean+np.multiply(np.sqrt(np.exp(z_log_sigma_sq)), eps))
      try:
              samples = self.sess.run(
                self.sampler,
                feed_dict={
                    self.z: sample_z,
                },
              )
              save_images(image, image_manifold_size(image.shape[0]),
                    './{}/train_{:02d}_{:04d}(original).png'.format(config.sample_dir, epoch, idx))
              save_images(samples, image_manifold_size(samples.shape[0]),
                    './{}/train_{:02d}_{:04d}(reconstruction).png'.format(config.sample_dir, epoch, idx))
      except:
              print("one pic error!...")

